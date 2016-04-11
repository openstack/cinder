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
import stat

from oslo_concurrency import processutils as putils
from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _LI, _LE, _LW
from cinder import utils
from cinder.volume.targets import iscsi

LOG = logging.getLogger(__name__)


class IetAdm(iscsi.ISCSITarget):
    VERSION = '0.1'

    def __init__(self, *args, **kwargs):
        super(IetAdm, self).__init__(*args, **kwargs)
        self.iet_conf = self.configuration.safe_get('iet_conf')
        self.iscsi_iotype = self.configuration.safe_get('iscsi_iotype')
        self.auth_type = 'IncomingUser'
        self.iet_sessions = '/proc/net/iet/session'

    def _get_target(self, iqn):

        # Find existing iSCSI target session from /proc/net/iet/session
        #
        # tid:2 name:iqn.2010-10.org:volume-222
        #     sid:562950561399296 initiator:iqn.1994-05.com:5a6894679665
        #         cid:0 ip:192.168.122.1 state:active hd:none dd:none
        # tid:1 name:iqn.2010-10.org:volume-111
        #     sid:281475567911424 initiator:iqn.1994-05.com:5a6894679665
        #         cid:0 ip:192.168.122.1 state:active hd:none dd:none

        iscsi_target = 0
        try:
            with open(self.iet_sessions, 'r') as f:
                sessions = f.read()
        except Exception:
            LOG.exception(_LE("Failed to open iet session list for %s"), iqn)
            raise

        session_list = re.split('^tid:(?m)', sessions)[1:]
        for ses in session_list:
            m = re.match('(\d+) name:(\S+)\s+', ses)
            if m and iqn in m.group(2):
                return m.group(1)

        return iscsi_target

    def _get_iscsi_target(self, context, vol_id):
        pass

    def _get_target_and_lun(self, context, volume):

        # For ietadm dev starts at lun 0
        lun = 0

        # Using 0, ietadm tries to search empty tid for creating
        # new iSCSI target
        iscsi_target = 0

        # Find existing iSCSI target based on iqn
        iqn = '%svolume-%s' % (self.iscsi_target_prefix, volume['id'])
        iscsi_target = self._get_target(iqn)

        return iscsi_target, lun

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):

        config_auth = None
        vol_id = name.split(':')[1]

        # Check the target is already existing.
        tmp_tid = self._get_target(name)

        # Create a new iSCSI target. If a target already exists,
        # the command returns 234, but we ignore it.
        try:
            self._new_target(name, tid)
            tid = self._get_target(name)
            self._new_logicalunit(tid, lun, path)

            if chap_auth is not None:
                (username, password) = chap_auth
                config_auth = ' '.join((self.auth_type,) + chap_auth)
                self._new_auth(tid, self.auth_type, username, password)
        except putils.ProcessExecutionError:
            LOG.exception(_LE("Failed to create iscsi target for volume "
                              "id:%s"), vol_id)
            raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        # Update config file only if new scsi target is created.
        if not tmp_tid:
            self.update_config_file(name, tid, path, config_auth)

        return tid

    def update_config_file(self, name, tid, path, config_auth):

        conf_file = self.iet_conf
        vol_id = name.split(':')[1]

        # If config file does not exist, create a blank conf file and
        # add configuration for the volume on the new file.
        if not os.path.exists(conf_file):
            try:
                utils.execute("truncate", conf_file, "--size=0",
                              run_as_root=True)
            except putils.ProcessExecutionError:
                LOG.exception(_LE("Failed to create %(conf)s for volume "
                                  "id:%(vol_id)s"),
                              {'conf': conf_file, 'vol_id': vol_id})
                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        try:
            volume_conf = """
                    Target %s
                        %s
                        Lun 0 Path=%s,Type=%s
            """ % (name, config_auth, path, self._iotype(path))

            with utils.temporary_chown(conf_file):
                with open(conf_file, 'a+') as f:
                    f.write(volume_conf)
        except Exception:
            LOG.exception(_LE("Failed to update %(conf)s for volume "
                              "id:%(vol_id)s"),
                          {'conf': conf_file, 'vol_id': vol_id})
            raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_LI("Removing iscsi_target for volume: %s"), vol_id)

        try:
            self._delete_logicalunit(tid, lun)
            session_info = self._find_sid_cid_for_target(tid, vol_name, vol_id)
            if session_info:
                sid, cid = session_info
                self._force_delete_target(tid, sid, cid)

            self._delete_target(tid)
        except putils.ProcessExecutionError:
            LOG.exception(_LE("Failed to remove iscsi target for volume "
                              "id:%s"), vol_id)
            raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)

        vol_uuid_file = vol_name
        conf_file = self.iet_conf
        if os.path.exists(conf_file):
            try:
                with utils.temporary_chown(conf_file):
                    with open(conf_file, 'r+') as iet_conf_text:
                        full_txt = iet_conf_text.readlines()
                        new_iet_conf_txt = []
                        count = 0
                        for line in full_txt:
                            if count > 0:
                                count -= 1
                                continue
                            elif vol_uuid_file in line:
                                count = 2
                                continue
                            else:
                                new_iet_conf_txt.append(line)

                        iet_conf_text.seek(0)
                        iet_conf_text.truncate(0)
                        iet_conf_text.writelines(new_iet_conf_txt)
            except Exception:
                LOG.exception(_LE("Failed to update %(conf)s for volume id "
                                  "%(vol_id)s after removing iscsi target"),
                              {'conf': conf_file, 'vol_id': vol_id})
                raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)
        else:
            LOG.warning(_LW("Failed to update %(conf)s for volume id "
                            "%(vol_id)s after removing iscsi target. "
                            "%(conf)s does not exist."),
                        {'conf': conf_file, 'vol_id': vol_id})

    def _find_sid_cid_for_target(self, tid, name, vol_id):
        """Find sid, cid for existing iscsi target"""

        try:
            with open(self.iet_sessions, 'r') as f:
                sessions = f.read()
        except Exception as e:
            LOG.info(_LI("Failed to open iet session list for "
                         "%(vol_id)s: %(e)s"),
                     {'vol_id': vol_id, 'e': e})
            return None

        session_list = re.split('^tid:(?m)', sessions)[1:]
        for ses in session_list:
            m = re.match('(\d+) name:(\S+)\s+sid:(\d+).+\s+cid:(\d+)', ses)
            if m and tid in m.group(1) and name in m.group(2):
                return m.group(3), m.group(4)

    def _is_block(self, path):
        mode = os.stat(path).st_mode
        return stat.S_ISBLK(mode)

    def _iotype(self, path):
        if self.iscsi_iotype == 'auto':
            return 'blockio' if self._is_block(path) else 'fileio'
        else:
            return self.iscsi_iotype

    def _new_target(self, name, tid):
        """Create new scsi target using specified parameters.

        If the target already exists, ietadm returns
        'Invalid argument' and error code '234'.
        This should be ignored for ensure export case.
        """
        utils.execute('ietadm', '--op', 'new',
                      '--tid=%s' % tid,
                      '--params', 'Name=%s' % name,
                      run_as_root=True, check_exit_code=[0, 234])

    def _delete_target(self, tid):
        utils.execute('ietadm', '--op', 'delete',
                      '--tid=%s' % tid,
                      run_as_root=True)

    def _force_delete_target(self, tid, sid, cid):
        utils.execute('ietadm', '--op', 'delete',
                      '--tid=%s' % tid,
                      '--sid=%s' % sid,
                      '--cid=%s' % cid,
                      run_as_root=True)

    def show_target(self, tid, iqn=None):
        utils.execute('ietadm', '--op', 'show',
                      '--tid=%s' % tid,
                      run_as_root=True)

    def _new_logicalunit(self, tid, lun, path):
        """Attach a new volume to scsi target as a logical unit.

        If a logical unit exists on the specified target lun,
        ietadm returns 'File exists' and error code '239'.
        This should be ignored for ensure export case.
        """

        utils.execute('ietadm', '--op', 'new',
                      '--tid=%s' % tid,
                      '--lun=%d' % lun,
                      '--params',
                      'Path=%s,Type=%s' % (path, self._iotype(path)),
                      run_as_root=True, check_exit_code=[0, 239])

    def _delete_logicalunit(self, tid, lun):
        utils.execute('ietadm', '--op', 'delete',
                      '--tid=%s' % tid,
                      '--lun=%d' % lun,
                      run_as_root=True)

    def _new_auth(self, tid, type, username, password):
        utils.execute('ietadm', '--op', 'new',
                      '--tid=%s' % tid,
                      '--user',
                      '--params=%s=%s,Password=%s' % (type,
                                                      username,
                                                      password),
                      run_as_root=True)
