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

import os
import re
import select
import time
import traceback

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import ssh_utils
from cinder import utils

LOG = logging.getLogger(__name__)

retry_msgids = ['iSM31005', 'iSM31015', 'iSM42408', 'iSM42412', 'iSM19411']


def get_sleep_time_for_clone(retry_count):
    if retry_count < 19:
        return int(10.0 * (1.1 ** retry_count))
    else:
        return 60


class MStorageISMCLI(object):
    """SSH client."""

    def __init__(self, properties):
        super(MStorageISMCLI, self).__init__()

        self._sshpool = None
        self._properties = properties

    def _execute(self, command, expected_status=[0], raise_exec=True):
        return self._sync_execute(command, self._properties['diskarray_name'],
                                  expected_status, raise_exec)

    @coordination.synchronized('mstorage_ismcli_execute_{diskarray_name}')
    def _sync_execute(self, command, diskarray_name,
                      expected_status=[0], raise_exec=True):
        retry_flag = True
        retry_count = 0
        while retry_flag is True:
            try:
                out, err, status = self._cli_execute(command, expected_status,
                                                     False)
                if status != 0:
                    errflg = 0
                    errnum = out + err
                    LOG.debug('ismcli failed (errnum=%s).', errnum)
                    for retry_msgid in retry_msgids:
                        if errnum.find(retry_msgid) >= 0:
                            LOG.debug('`%(command)s` failed. '
                                      '%(name)s %(errnum)s '
                                      'retry_count=%(retry_count)d',
                                      {'command': command,
                                       'name': __name__,
                                       'errnum': errnum,
                                       'retry_count': retry_count})
                            errflg = 1
                            break
                    if errflg == 1:
                        retry_count += 1
                        if retry_count >= 60:
                            msg = (_('Timeout `%(command)s`.'
                                     ' status=%(status)d, '
                                     'out="%(out)s", '
                                     'err="%(err)s".') %
                                   {'command': command,
                                    'status': status,
                                    'out': out,
                                    'err': err})
                            raise exception.APITimeout(msg)
                        time.sleep(5)
                        continue
                    else:
                        if raise_exec is True:
                            msg = _('Command `%s` failed.') % command
                            raise exception.VolumeBackendAPIException(data=msg)
            except EOFError:
                with excutils.save_and_reraise_exception() as ctxt:
                    LOG.debug('EOFError has occurred. '
                              '%(name)s retry_count=%(retry_count)d',
                              {'name': __name__,
                               'retry_count': retry_count})
                    retry_count += 1
                    if retry_count < 60:
                        ctxt.reraise = False
                time.sleep(5)
                continue
            retry_flag = False

        return out, err, status

    def _execute_nolock(self, command, expected_status=[0], raise_exec=True):
        retry_flag = True
        retry_count = 0
        while retry_flag is True:
            try:
                out, err, status = self._cli_execute(command, expected_status,
                                                     raise_exec)
            except EOFError:
                with excutils.save_and_reraise_exception() as ctxt:
                    LOG.debug('EOFError has occurred. '
                              '%(name)s retry_count=%(retry_count)d',
                              {'name': __name__,
                               'retry_count': retry_count})
                    retry_count += 1
                    if retry_count < 60:
                        ctxt.reraise = False
                time.sleep(5)
                continue
            retry_flag = False
        return out, err, status

    def _cli_execute(self, command, expected_status=[0], raise_exec=True):
        if not self._sshpool:
            LOG.debug('ssh_utils.SSHPool execute.')
            self._sshpool = ssh_utils.SSHPool(
                self._properties['cli_fip'],
                self._properties['ssh_pool_port_number'],
                self._properties['ssh_conn_timeout'],
                self._properties['cli_user'],
                self._properties['cli_password'],
                privatekey=self._properties['cli_privkey'])

        with self._sshpool.item() as ssh:
            LOG.debug('`%s` executing...', command)
            stdin, stdout, stderr = ssh.exec_command(command)
            stdin.close()
            channel = stdout.channel
            tmpout, tmperr = b'', b''
            while 1:
                select.select([channel], [], [])
                if channel.recv_ready():
                    tmpout += channel.recv(4096)
                    continue
                if channel.recv_stderr_ready():
                    tmperr += channel.recv_stderr(4096)
                    continue
                if channel.exit_status_ready():
                    status = channel.recv_exit_status()
                    break
            LOG.debug('`%(command)s` done. status=%(status)d.',
                      {'command': command, 'status': status})
            out = utils.convert_str(tmpout)
            err = utils.convert_str(tmperr)
            if expected_status is not None and status not in expected_status:
                LOG.debug('`%(command)s` failed. status=%(status)d, '
                          'out="%(out)s", err="%(err)s".',
                          {'command': command, 'status': status,
                           'out': out, 'err': err})
                if raise_exec is True:
                    msg = _('Command `%s` failed.') % command
                    raise exception.VolumeBackendAPIException(data=msg)
            return out, err, status

    def view_all(self, conf_ismview_path=None, delete_ismview=True,
                 cmd_lock=True):
        if self._properties['queryconfig_view'] is True:
            command = 'clioutmsg xml; iSMview'
            if self._properties['ismview_alloptimize'] is True:
                command += ' --alloptimize'
            else:
                command += ' -all'
        else:
            command = 'iSMquery -cinder -xml -all'
        if cmd_lock is True:
            out, err, status = self._execute(command)
        else:
            out, err, status = self._execute_nolock(command)

        exstats = re.compile(r"(.*)ExitStatus(.*)\n")
        tmpout = exstats.sub('', out)
        out = tmpout
        if conf_ismview_path is not None:
            if delete_ismview:
                if os.path.exists(conf_ismview_path):
                    os.remove(conf_ismview_path)
                    LOG.debug('Remove clioutmsg xml to %s.',
                              conf_ismview_path)
            else:
                with open(conf_ismview_path, 'w+') as f:
                    f.write(out)
                    LOG.debug('Wrote clioutmsg xml to %s.',
                              conf_ismview_path)
        return out

    def ldbind(self, name, pool, ldn, size):
        """Bind an LD and attach a nickname to it."""
        errnum = ""
        cmd = ('iSMcfg ldbind -poolnumber %(poolnumber)d -ldn %(ldn)d '
               '-capacity %(capacity)d -immediate'
               % {'poolnumber': pool, 'ldn': ldn,
                  'capacity': size})
        out, err, status = self._execute(cmd, [0], False)
        errnum = err
        if status != 0:
            return False, errnum

        cmd = ('iSMcfg nickname -ldn %(ldn)d -newname %(newname)s '
               '-immediate'
               % {'ldn': ldn, 'newname': name})
        self._execute(cmd)
        return True, errnum

    def unbind(self, name):
        """Unbind an LD."""
        cmd = 'iSMcfg ldunbind -ldname %s' % name
        self._execute(cmd)

    def expand(self, ldn, capacity):
        """Expand a LD."""
        cmd = ('iSMcfg ldexpand -ldn %(ldn)d -capacity %(capacity)d '
               '-unit gb'
               % {'ldn': ldn, 'capacity': capacity})
        self._execute(cmd)

    def addldset_fc(self, ldsetname, connector):
        """Create new FC LD Set."""
        cmd = 'iSMcfg addldset -ldset LX:%s -type fc' % ldsetname
        out, err, status = self._execute(cmd, [0], False)
        if status != 0:
            return False
        for wwpn in connector['wwpns']:
            length = len(wwpn)
            setwwpn = '-'.join([wwpn[i:i + 4]
                                for i in range(0, length, 4)])
            setwwpn = setwwpn.upper()
            cmd = ('iSMcfg addldsetpath -ldset LX:%(name)s -path %(path)s'
                   % {'name': ldsetname, 'path': setwwpn})
            out, err, status = self._execute(cmd, [0], False)
            if status != 0:
                return False

        return True

    def addldset_iscsi(self, ldsetname, connector):
        """Create new iSCSI LD Set."""
        cmd = ('iSMcfg addldset -ldset LX:%s -type iscsi' % ldsetname)
        out, err, status = self._execute(cmd, [0], False)
        if status != 0:
            return False
        cmd = ('iSMcfg addldsetinitiator'
               ' -ldset LX:%(name)s -initiatorname %(initiator)s'
               % {'name': ldsetname, 'initiator': connector['initiator']})
        out, err, status = self._execute(cmd, [0], False)
        if status != 0:
            return False

        return True

    def addldsetld(self, ldset, ldname, lun=None):
        """Add an LD to specified LD Set."""
        if lun is None:
            cmd = ('iSMcfg addldsetld -ldset %(ldset)s '
                   '-ldname %(ldname)s'
                   % {'ldset': ldset, 'ldname': ldname})
            self._execute(cmd)
        else:
            cmd = ('iSMcfg addldsetld -ldset %(ldset)s -ldname %(ldname)s '
                   '-lun %(lun)d'
                   % {'ldset': ldset, 'ldname': ldname,
                      'lun': lun})
            self._execute(cmd)

    def delldsetld(self, ldset, ldname):
        """Delete an LD from specified LD Set."""
        rtn = True
        errnum = ""
        cmd = ('iSMcfg delldsetld -ldset %(ldset)s '
               '-ldname %(ldname)s'
               % {'ldset': ldset,
                  'ldname': ldname})
        out, err, status = self._execute(cmd, [0], False)
        errnum = err
        if status != 0:
            rtn = False
        return rtn, errnum

    def changeldname(self, ldn, new_name, old_name=None):
        """Rename nickname of LD."""
        if old_name is None:
            cmd = ('iSMcfg nickname -ldn %(ldn)d -newname %(newname)s '
                   '-immediate'
                   % {'ldn': ldn, 'newname': new_name})
            self._execute(cmd)
        else:
            cmd = ('iSMcfg nickname -ldname %(ldname)s '
                   '-newname %(newname)s'
                   % {'ldname': old_name,
                      'newname': new_name})
            self._execute(cmd)

    def setpair(self, mvname, rvname):
        """Set pair."""
        cmd = ('iSMrc_pair -pair -mv %(mv)s -mvflg ld '
               '-rv %(rv)s -rvflg ld'
               % {'mv': mvname, 'rv': rvname})
        self._execute(cmd)

        LOG.debug('Pair command completed. MV = %(mv)s RV = %(rv)s.',
                  {'mv': mvname, 'rv': rvname})

    def unpair(self, mvname, rvname, flag):
        """Unset pair."""
        if flag == 'normal':
            cmd = ('iSMrc_pair -unpair -mv %(mv)s -mvflg ld '
                   '-rv %(rv)s -rvflg ld'
                   % {'mv': mvname, 'rv': rvname})
            self._execute(cmd)
        elif flag == 'force':
            cmd = ('iSMrc_pair -unpair -mv %(mv)s -mvflg ld '
                   '-rv %(rv)s -rvflg ld -force all'
                   % {'mv': mvname, 'rv': rvname})
            self._execute(cmd)
        else:
            LOG.debug('unpair flag ERROR. flag = %s', flag)

        LOG.debug('Unpair command completed. MV = %(mv)s, RV = %(rv)s.',
                  {'mv': mvname, 'rv': rvname})

    def replicate(self, mvname, rvname, flag):
        if flag == 'full':
            cmd = ('iSMrc_replicate -mv %(mv)s -mvflg ld '
                   '-rv %(rv)s -rvflg ld -nowait -cprange full '
                   '-cpmode bg'
                   % {'mv': mvname, 'rv': rvname})
            self._execute(cmd)
        else:
            cmd = ('iSMrc_replicate -mv %(mv)s -mvflg ld '
                   '-rv %(rv)s -rvflg ld -nowait -cpmode bg'
                   % {'mv': mvname, 'rv': rvname})
            self._execute(cmd)

        LOG.debug('Replicate command completed. MV = %(mv)s RV = %(rv)s.',
                  {'mv': mvname, 'rv': rvname})

    def separate(self, mvname, rvname, flag):
        """Separate for backup."""
        if flag == 'backup':
            cmd = ('iSMrc_separate -mv %(mv)s -mvflg ld '
                   '-rv %(rv)s -rvflg ld '
                   '-rvacc ro -rvuse complete -nowait'
                   % {'mv': mvname, 'rv': rvname})
            self._execute(cmd)
        elif flag == 'restore' or flag == 'clone':
            cmd = ('iSMrc_separate -mv %(mv)s -mvflg ld '
                   '-rv %(rv)s -rvflg ld '
                   '-rvacc rw -rvuse immediate -nowait'
                   % {'mv': mvname, 'rv': rvname})
            self._execute(cmd)
        elif flag == 'esv_restore' or flag == 'migrate':
            cmd = ('iSMrc_separate -mv %(mv)s -mvflg ld '
                   '-rv %(rv)s -rvflg ld '
                   '-rvacc rw -rvuse complete -nowait'
                   % {'mv': mvname, 'rv': rvname})
            self._execute(cmd)
        else:
            LOG.debug('separate flag ERROR. flag = %s', flag)

        LOG.debug('Separate command completed. MV = %(mv)s RV = %(rv)s.',
                  {'mv': mvname, 'rv': rvname})

    def query_MV_RV_status(self, ldname, rpltype):
        if rpltype == 'MV':
            cmd = ('iSMrc_query -mv %s -mvflg ld | '
                   'while builtin read line;'
                   'do if [[ "$line" =~ "Sync State" ]]; '
                   'then builtin echo ${line:10};fi;'
                   'done' % ldname)
            out, err, status = self._execute(cmd)
        elif rpltype == 'RV':
            cmd = ('iSMrc_query -rv %s -rvflg ld | '
                   'while builtin read line;'
                   'do if [[ "$line" =~ "Sync State" ]]; '
                   'then builtin echo ${line:10};fi;'
                   'done' % ldname)
            out, err, status = self._execute(cmd)
        else:
            LOG.debug('rpltype flag ERROR. rpltype = %s', rpltype)

        query_status = out.strip()
        return query_status

    def query_MV_RV_name(self, ldname, rpltype):
        if rpltype == 'MV':
            cmd = ('iSMrc_query -mv %s -mvflg ld | '
                   'while builtin read line;'
                   'do if [[ "$line" =~ "LD Name" ]]; '
                   'then builtin echo ${line:7};fi;'
                   'done' % ldname)
            out, err, status = self._execute(cmd)
            out = out.replace(ldname, "")
        elif rpltype == 'RV':
            cmd = ('iSMrc_query -rv %s -rvflg ld | '
                   'while builtin read line;'
                   'do if [[ "$line" =~ "LD Name" ]]; '
                   'then builtin echo ${line:7};fi;'
                   'done' % ldname)
            out, err, status = self._execute(cmd)
            out = out.replace(ldname, "")
        else:
            LOG.debug('rpltype flag ERROR. rpltype = %s', rpltype)

        query_name = out.strip()
        return query_name

    def query_MV_RV_diff(self, ldname, rpltype):
        if rpltype == 'MV':
            cmd = ('iSMrc_query -mv %s -mvflg ld | '
                   'while builtin read line;'
                   'do if [[ "$line" =~ "Separate Diff" ]]; '
                   'then builtin echo ${line:13};fi;'
                   'done' % ldname)
            out, err, status = self._execute(cmd)
        elif rpltype == 'RV':
            cmd = ('iSMrc_query -rv %s -rvflg ld | '
                   'while builtin read line;'
                   'do if [[ "$line" =~ "Separate Diff" ]]; '
                   'then builtin echo ${line:13};fi;'
                   'done' % ldname)
            out, err, status = self._execute(cmd)
        else:
            LOG.debug('rpltype flag ERROR. rpltype = %s', rpltype)

        query_status = out.strip()
        return query_status

    def backup_restore(self, volume_properties, unpairWait, canPairing=True):

        # Setting Pair.
        flag = 'full'
        if canPairing is True:
            self.setpair(volume_properties['mvname'][3:],
                         volume_properties['rvname'][3:])
        else:
            rv_diff = self.query_MV_RV_diff(volume_properties['rvname'][3:],
                                            'RV')
            rv_diff = int(rv_diff.replace('KB', ''), 10) // units.Ki
            if rv_diff != volume_properties['capacity']:
                flag = None

        # Replicate.
        self.replicate(volume_properties['mvname'][3:],
                       volume_properties['rvname'][3:], flag)

        # Separate.
        self.separate(volume_properties['mvname'][3:],
                      volume_properties['rvname'][3:],
                      volume_properties['flag'])

        unpairProc = unpairWait(volume_properties, self)
        unpairProc.run()

    def check_ld_existed_rplstatus(self, lds, ldname, snapshot, flag):

        if ldname not in lds:
            if flag == 'backup':
                LOG.debug('Volume Id not found. '
                          'LD name = %(name)s volume_id = %(id)s.',
                          {'name': ldname, 'id': snapshot.volume_id})
                raise exception.NotFound(_('Logical Disk does not exist.'))
            elif flag == 'restore':
                LOG.debug('Snapshot Id not found. '
                          'LD name = %(name)s snapshot_id = %(id)s.',
                          {'name': ldname, 'id': snapshot.id})
                raise exception.NotFound(_('Logical Disk does not exist.'))
            elif flag == 'delete':
                LOG.debug('LD `%(name)s` already unbound? '
                          'snapshot_id = %(id)s.',
                          {'name': ldname, 'id': snapshot.id})
                return None
            else:
                LOG.debug('check_ld_existed_rplstatus flag error flag = %s.',
                          flag)
                raise exception.NotFound(_('Logical Disk does not exist.'))

        ld = lds[ldname]

        if ld['RPL Attribute'] == 'IV':
            pass
        elif ld['RPL Attribute'] == 'MV':
            query_status = self.query_MV_RV_status(ldname[3:], 'MV')
            LOG.debug('query_status : %s.', query_status)
            if(query_status == 'separated'):
                # unpair.
                rvname = self.query_MV_RV_name(ldname[3:], 'MV')
                self.unpair(ldname[3:], rvname, 'force')
            else:
                msg = _('Specified Logical Disk %s has been copied.') % ldname
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        elif ld['RPL Attribute'] == 'RV':
            query_status = self.query_MV_RV_status(ldname[3:], 'RV')
            if query_status == 'separated':
                # unpair.
                mvname = self.query_MV_RV_name(ldname[3:], 'RV')
                self.unpair(mvname, ldname[3:], 'force')
            else:
                msg = _('Specified Logical Disk %s has been copied.') % ldname
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

        return ld

    def get_pair_lds(self, ldname, lds):
        query_status = self.query_MV_RV_name(ldname[3:], 'MV')
        query_status = query_status.split('\n')
        query_status = [query for query in query_status if query != '']
        LOG.debug('query_status=%s.', query_status)

        pair_lds = {}
        for rvname in query_status:
            rvname = self._properties['ld_backupname_format'] % rvname
            if rvname not in lds:
                LOG.debug('LD `%s` is RDR pair?', rvname)
            else:
                ld = lds[rvname]
                ldn = ld['ldn']
                pair_lds[ldn] = ld

        LOG.debug('pair_lds=%s.', pair_lds)
        return pair_lds

    def snapshot_create(self, bvname, svname, poolnumber):
        """Snapshot create."""
        cmd = ('iSMcfg generationadd -bvname %(bvname)s '
               '-poolnumber %(poolnumber)d -count 1 '
               '-svname %(svname)s'
               % {'bvname': bvname,
                  'poolnumber': poolnumber,
                  'svname': svname})
        self._execute(cmd)

        cmd = ('iSMsc_create -bv %(bv)s -bvflg ld -sv %(sv)s '
               '-svflg ld'
               % {'bv': bvname[3:], 'sv': svname})
        self._execute(cmd)

    def snapshot_delete(self, bvname, svname):
        """Snapshot delete."""
        query_status = self.query_BV_SV_status(bvname[3:], svname)
        if query_status == 'snap/active':
            cmd = ('iSMsc_delete -bv %(bv)s -bvflg ld -sv %(sv)s '
                   '-svflg ld'
                   % {'bv': bvname[3:], 'sv': svname})
            self._execute(cmd)

            while True:
                query_status = self.query_BV_SV_status(bvname[3:], svname)
                if query_status == 'snap/deleting':
                    LOG.debug('Sleep 1 seconds Start')
                    time.sleep(1)
                else:
                    break
        else:
            LOG.debug('The snapshot data does not exist,'
                      ' because already forced deletion.'
                      ' bvname=%(bvname)s, svname=%(svname)s',
                      {'bvname': bvname, 'svname': svname})

        cmd = 'iSMcfg generationdel -bvname %s -count 1' % bvname
        self._execute(cmd)

    def snapshot_restore(self, bvname, svname):
        """Snapshot restore."""
        query_status = self.query_BV_SV_status(bvname[3:], svname[3:])
        if query_status == 'snap/active':
            cmd = ('iSMsc_restore -bv %(bv)s -bvflg ld -sv %(sv)s '
                   '-svflg ld -derivsv keep -nowait'
                   % {'bv': bvname[3:], 'sv': svname[3:]})
            self._execute(cmd)

            retry_count = 0
            while True:
                query_status = self.query_BV_SV_status(bvname[3:], svname[3:])
                if query_status == 'rst/exec':
                    # Restoration is in progress.
                    sleep_time = get_sleep_time_for_clone(retry_count)
                    LOG.debug('Sleep %d seconds Start', sleep_time)
                    time.sleep(sleep_time)
                    retry_count += 1
                elif query_status == 'snap/active':
                    # Restoration was successful.
                    break
                else:
                    # Restoration failed.
                    msg = (_('Failed to restore from snapshot. '
                             'bvname=%(bvname)s, svname=%(svname)s, '
                             'status=%(status)s') %
                           {'bvname': bvname, 'svname': svname,
                            'status': query_status})
                    LOG.error(msg)
                    raise exception.VolumeBackendAPIException(data=msg)
        else:
            msg = (_('The snapshot does not exist or is '
                     'not in snap/active status. '
                     'bvname=%(bvname)s, svname=%(svname)s, '
                     'status=%(status)s') %
                   {'bvname': bvname, 'svname': svname,
                    'status': query_status})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def query_BV_SV_status(self, bvname, svname):
        cmd = ('iSMsc_query -bv %(bv)s -bvflg ld -sv %(sv)s -svflg ld '
               '-summary | '
               'while builtin read line;do '
               'if [[ "$line" =~ "%(line)s" ]]; '
               'then builtin echo "$line";fi;done'
               % {'bv': bvname, 'sv': svname, 'line': svname})
        out, err, status = self._execute(cmd)

        delimiter = ') '
        start = out.find(delimiter)
        if start == -1:
            return None
        start += len(delimiter)
        query_status = out[start:].split(' ')[0]
        LOG.debug('snap/state:%s.', query_status)
        return query_status

    def get_bvname(self, svname):
        cmd = ('iSMsc_query -sv %s -svflg ld -summary | '
               'while builtin read line;do '
               'if [[ "$line" =~ "LD Name" ]]; '
               'then builtin echo "$line";fi;done'
               % svname[3:])
        out, err, status = self._execute(cmd)

        query_status = out[15:39].strip()
        return query_status

    def set_io_limit(self, ldname, qos_params, force_delete=True):
        upper = qos_params['upperlimit']
        lower = qos_params['lowerlimit']
        report = qos_params['upperreport']
        if upper is None and lower is None and report is None:
            return
        cmd = 'iSMioc setlimit -ldname %s' % ldname
        if upper is not None:
            cmd += ' -upperlimit %d' % upper
        if lower is not None:
            cmd += ' -lowerlimit %d' % lower
        if report is not None:
            cmd += ' -upperreport %s' % report
        try:
            self._execute(cmd)
        except Exception:
            with excutils.save_and_reraise_exception():
                if force_delete:
                    self.unbind(ldname)

    def lvbind(self, bvname, lvname, lvnumber):
        """Link Volume create."""
        cmd = ('iSMcfg lvbind -bvname %(bvname)s '
               '-lvn %(lvnumber)d -lvname %(lvname)s'
               % {'bvname': bvname,
                  'lvnumber': lvnumber,
                  'lvname': lvname})
        self._execute(cmd)

    def lvunbind(self, lvname):
        """Link Volume delete."""
        cmd = ('iSMcfg lvunbind -ldname %(lvname)s'
               % {'lvname': lvname})
        self._execute(cmd)

    def lvlink(self, svname, lvname):
        """Link to snapshot volume."""
        cmd = ('iSMsc_link -lv %(lvname)s -lvflg ld '
               '-sv %(svname)s -svflg ld -lvacc ro'
               % {'lvname': lvname,
                  'svname': svname})
        self._execute(cmd)

    def lvunlink(self, lvname):
        """Unlink from snapshot volume."""
        cmd = ('iSMsc_unlink -lv %(lvname)s -lvflg ld'
               % {'lvname': lvname})
        self._execute(cmd)

    def cvbind(self, poolnumber, cvnumber):
        """Create Control Volume."""
        cmd = ('iSMcfg ldbind -poolnumber %(poolnumber)d '
               '-ldattr cv -ldn %(cvnumber)d'
               % {'poolnumber': poolnumber,
                  'cvnumber': cvnumber})
        self._execute(cmd)


class UnpairWait(object):

    def __init__(self, volume_properties, cli):
        super(UnpairWait, self).__init__()
        self._volume_properties = volume_properties
        self._mvname = volume_properties['mvname'][3:]
        self._rvname = volume_properties['rvname'][3:]
        self._mvID = volume_properties['mvid']
        self._rvID = volume_properties['rvid']
        self._flag = volume_properties['flag']
        self._context = volume_properties['context']
        self._cli = cli
        self._local_conf = self._cli._properties

    def _wait(self, unpair=True):
        timeout = self._local_conf['thread_timeout'] * 24
        start_time = time.time()
        retry_count = 0
        while True:
            cur_time = time.time()
            if (cur_time - start_time) > timeout:
                raise exception.APITimeout(_('UnpairWait wait timeout.'))

            sleep_time = get_sleep_time_for_clone(retry_count)
            LOG.debug('Sleep %d seconds Start', sleep_time)
            time.sleep(sleep_time)
            retry_count += 1

            query_status = self._cli.query_MV_RV_status(self._rvname, 'RV')
            if query_status == 'separated':
                if unpair is True:
                    self._cli.unpair(self._mvname, self._rvname, 'normal')
                break
            elif query_status == 'sep/exec':
                continue
            else:
                LOG.debug('iSMrc_query command result abnormal.'
                          'Query status = %(status)s, RV = %(rv)s.',
                          {'status': query_status, 'rv': self._rvname})
                break

    def run(self):
        try:
            self._execute()
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.debug('UnpairWait Unexpected error. '
                          'exception=%(exception)s, MV = %(mv)s, RV = %(rv)s.',
                          {'exception': traceback.format_exc(),
                           'mv': self._mvname, 'rv': self._rvname})

    def _execute(self):
        pass


class UnpairWaitForRestore(UnpairWait):
    def __init__(self, volume_properties, cli):
        super(UnpairWaitForRestore, self).__init__(volume_properties, cli)

        self._rvldn = None
        if ('rvldn' in volume_properties and
                volume_properties['rvldn'] is not None):
            self._rvldn = volume_properties['rvldn']

        self._rvcapacity = None
        if ('rvcapacity' in volume_properties and
                volume_properties['rvcapacity'] is not None):
            self._rvcapacity = volume_properties['rvcapacity']

    def _execute(self):
        LOG.debug('UnpairWaitForRestore start.')

        self._wait(True)

        if self._rvcapacity is not None:
            try:
                self._cli.expand(self._rvldn, self._rvcapacity)
            except exception.CinderException:
                with excutils.save_and_reraise_exception():
                    LOG.debug('UnpairWaitForDDRRestore expand error. '
                              'exception=%(exception)s, '
                              'MV = %(mv)s, RV = %(rv)s.',
                              {'exception': traceback.format_exc(),
                               'mv': self._mvname, 'rv': self._rvname})


class UnpairWaitForClone(UnpairWait):
    def __init__(self, volume_properties, cli):
        super(UnpairWaitForClone, self).__init__(volume_properties, cli)

        self._rvldn = None
        if ('rvldn' in volume_properties and
                volume_properties['rvldn'] is not None):
            self._rvldn = volume_properties['rvldn']

        self._rvcapacity = None
        if ('rvcapacity' in volume_properties and
                volume_properties['rvcapacity'] is not None):
            self._rvcapacity = volume_properties['rvcapacity']

    def _execute(self):
        LOG.debug('UnpairWaitForClone start.')

        self._wait(True)

        if self._rvcapacity is not None:
            try:
                self._cli.expand(self._rvldn, self._rvcapacity)
            except exception.CinderException:
                with excutils.save_and_reraise_exception():
                    LOG.debug('UnpairWaitForClone expand error. '
                              'exception=%(exception)s, '
                              'MV = %(mv)s, RV = %(rv)s.',
                              {'exception': traceback.format_exc(),
                               'mv': self._mvname, 'rv': self._rvname})


class UnpairWaitForMigrate(UnpairWait):
    def __init__(self, volume_properties, cli):
        super(UnpairWaitForMigrate, self).__init__(volume_properties, cli)

    def _execute(self):
        LOG.debug('UnpairWaitForMigrate start.')

        self._wait(True)

        self._cli.unbind(self._volume_properties['mvname'])
        self._cli.changeldname(None, self._volume_properties['mvname'],
                               self._volume_properties['rvname'])


class UnpairWaitForDDRRestore(UnpairWaitForRestore):
    def __init__(self, volume_properties, cli):
        super(UnpairWaitForDDRRestore, self).__init__(volume_properties, cli)

        self._prev_mvname = None
        if ('prev_mvname' in volume_properties and
                volume_properties['prev_mvname'] is not None):
            self._prev_mvname = volume_properties['prev_mvname'][3:]

    def _execute(self):
        LOG.debug('UnpairWaitForDDRRestore start.')

        self._wait(True)

        if self._rvcapacity is not None:
            try:
                self._cli.expand(self._rvldn, self._rvcapacity)
            except exception.CinderException:
                with excutils.save_and_reraise_exception():
                    LOG.debug('UnpairWaitForDDRRestore expand error. '
                              'exception=%(exception)s, '
                              'MV = %(mv)s, RV = %(rv)s.',
                              {'exception': traceback.format_exc(),
                               'mv': self._mvname, 'rv': self._rvname})

        if self._prev_mvname is not None:
            self._cli.setpair(self._prev_mvname, self._mvname)
