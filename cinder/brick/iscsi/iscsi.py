# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Helper code for the iSCSI volume driver.

"""

import contextlib
import os
import re
import stat

from oslo.config import cfg

from cinder.brick import exception
from cinder.brick import executor
from cinder.openstack.common import fileutils
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils


LOG = logging.getLogger(__name__)

iscsi_helper_opt = [cfg.StrOpt('iscsi_helper',
                               default='tgtadm',
                               help='iscsi target user-land tool to use'),
                    cfg.StrOpt('volumes_dir',
                               default='$state_path/volumes',
                               help='Volume configuration file storage '
                                    'directory'),
                    cfg.StrOpt('iet_conf',
                               default='/etc/iet/ietd.conf',
                               help='IET configuration file'),
                    cfg.StrOpt('lio_initiator_iqns',
                               default='',
                               help=('Comma-separatd list of initiator IQNs '
                                     'allowed to connect to the '
                                     'iSCSI target. (From Nova compute nodes.)'
                                     )
                               ),
                    cfg.StrOpt('iscsi_iotype',
                               default='fileio',
                               help=('Sets the behavior of the iSCSI target '
                                     'to either perform blockio or fileio '
                                     'optionally, auto can be set and Cinder '
                                     'will autodetect type of backing device')
                               )
                    ]

CONF = cfg.CONF
CONF.register_opts(iscsi_helper_opt)


class TargetAdmin(executor.Executor):
    """iSCSI target administration.

    Base class for iSCSI target admin helpers.
    """

    def __init__(self, cmd, root_helper, execute):
        super(TargetAdmin, self).__init__(root_helper, execute=execute)
        self._cmd = cmd

    def _run(self, *args, **kwargs):
        self._execute(self._cmd, *args, run_as_root=True, **kwargs)

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):
        """Create a iSCSI target and logical unit."""
        raise NotImplementedError()

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        """Remove a iSCSI target and logical unit"""
        raise NotImplementedError()

    def _new_target(self, name, tid, **kwargs):
        """Create a new iSCSI target."""
        raise NotImplementedError()

    def _delete_target(self, tid, **kwargs):
        """Delete a target."""
        raise NotImplementedError()

    def show_target(self, tid, iqn=None, **kwargs):
        """Query the given target ID."""
        raise NotImplementedError()

    def _new_logicalunit(self, tid, lun, path, **kwargs):
        """Create a new LUN on a target using the supplied path."""
        raise NotImplementedError()

    def _delete_logicalunit(self, tid, lun, **kwargs):
        """Delete a logical unit from a target."""
        raise NotImplementedError()


class TgtAdm(TargetAdmin):
    """iSCSI target administration using tgtadm."""

    def __init__(self, root_helper, execute=putils.execute):
        super(TgtAdm, self).__init__('tgtadm', root_helper, execute)

    def _get_target(self, iqn):
        (out, err) = self._execute('tgt-admin', '--show', run_as_root=True)
        lines = out.split('\n')
        for line in lines:
            if iqn in line:
                parsed = line.split()
                tid = parsed[1]
                return tid[:-1]

        return None

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):
        # Note(jdg) tid and lun aren't used by TgtAdm but remain for
        # compatibility

        fileutils.ensure_tree(CONF.volumes_dir)

        vol_id = name.split(':')[1]
        if chap_auth is None:
            volume_conf = """
                <target %s>
                    backing-store %s
                </target>
            """ % (name, path)
        else:
            volume_conf = """
                <target %s>
                    backing-store %s
                    %s
                </target>
            """ % (name, path, chap_auth)

        LOG.info(_('Creating iscsi_target for: %s') % vol_id)
        volumes_dir = CONF.volumes_dir
        volume_path = os.path.join(volumes_dir, vol_id)

        f = open(volume_path, 'w+')
        f.write(volume_conf)
        f.close()

        old_persist_file = None
        old_name = kwargs.get('old_name', None)
        if old_name is not None:
            old_persist_file = os.path.join(volumes_dir, old_name)

        try:
            (out, err) = self._execute('tgt-admin',
                                       '--update',
                                       name,
                                       run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to create iscsi target for volume "
                        "id:%(vol_id)s: %(e)s")
                      % {'vol_id': vol_id, 'e': str(e)})

            #Don't forget to remove the persistent file we created
            os.unlink(volume_path)
            raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        iqn = '%s%s' % (CONF.iscsi_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.error(_("Failed to create iscsi target for volume "
                        "id:%(vol_id)s. Please ensure your tgtd config file "
                        "contains 'include %(volumes_dir)s/*'") % {
                            'vol_id': vol_id,
                            'volumes_dir': volumes_dir,
                        })
            raise exception.NotFound()

        if old_persist_file is not None and os.path.exists(old_persist_file):
            os.unlink(old_persist_file)

        return tid

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_('Removing iscsi_target for: %s') % vol_id)
        vol_uuid_file = vol_name
        volume_path = os.path.join(CONF.volumes_dir, vol_uuid_file)
        if os.path.isfile(volume_path):
            iqn = '%s%s' % (CONF.iscsi_target_prefix,
                            vol_uuid_file)
        else:
            raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)
        try:
            # NOTE(vish): --force is a workaround for bug:
            #             https://bugs.launchpad.net/cinder/+bug/1159948
            self._execute('tgt-admin',
                          '--force',
                          '--delete',
                          iqn,
                          run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to remove iscsi target for volume "
                        "id:%(vol_id)s: %(e)s")
                      % {'vol_id': vol_id, 'e': str(e)})
            raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)

        os.unlink(volume_path)

    def show_target(self, tid, iqn=None, **kwargs):
        if iqn is None:
            raise exception.InvalidParameterValue(
                err=_('valid iqn needed for show_target'))

        tid = self._get_target(iqn)
        if tid is None:
            raise exception.NotFound()


class IetAdm(TargetAdmin):
    """iSCSI target administration using ietadm."""

    def __init__(self, root_helper, execute=putils.execute):
        super(IetAdm, self).__init__('ietadm', root_helper, execute)

    def _is_block(self, path):
        mode = os.stat(path).st_mode
        return stat.S_ISBLK(mode)

    def _iotype(self, path):
        if CONF.iscsi_iotype == 'auto':
            return 'blockio' if self._is_block(path) else 'fileio'
        else:
            return CONF.iscsi_iotype

    @contextlib.contextmanager
    def temporary_chown(self, path, owner_uid=None):
        """Temporarily chown a path.

        :params path: The path to chown
        :params owner_uid: UID of temporary owner (defaults to current user)
        """
        if owner_uid is None:
            owner_uid = os.getuid()

        orig_uid = os.stat(path).st_uid

        if orig_uid != owner_uid:
            putils.execute('chown', owner_uid, path, run_as_root=True)
        try:
            yield
        finally:
            if orig_uid != owner_uid:
                putils.execute('chown', orig_uid, path, run_as_root=True)

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):

        # NOTE (jdg): Address bug: 1175207
        kwargs.pop('old_name', None)

        self._new_target(name, tid, **kwargs)
        self._new_logicalunit(tid, lun, path, **kwargs)
        if chap_auth is not None:
            (type, username, password) = chap_auth.split()
            self._new_auth(tid, type, username, password, **kwargs)

        conf_file = CONF.iet_conf
        if os.path.exists(conf_file):
            try:
                volume_conf = """
                        Target %s
                            %s
                            Lun 0 Path=%s,Type=%s
                """ % (name, chap_auth, path, self._iotype(path))

                with self.temporary_chown(conf_file):
                    f = open(conf_file, 'a+')
                    f.write(volume_conf)
                    f.close()
            except putils.ProcessExecutionError as e:
                vol_id = name.split(':')[1]
                LOG.error(_("Failed to create iscsi target for volume "
                            "id:%(vol_id)s: %(e)s")
                          % {'vol_id': vol_id, 'e': str(e)})
                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)
        return tid

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_('Removing iscsi_target for volume: %s') % vol_id)
        self._delete_logicalunit(tid, lun, **kwargs)
        self._delete_target(tid, **kwargs)
        vol_uuid_file = vol_name
        conf_file = CONF.iet_conf
        if os.path.exists(conf_file):
            with self.temporary_chown(conf_file):
                try:
                    iet_conf_text = open(conf_file, 'r+')
                    full_txt = iet_conf_text.readlines()
                    new_iet_conf_txt = []
                    count = 0
                    for line in full_txt:
                        if count > 0:
                            count -= 1
                            continue
                        elif re.search(vol_uuid_file, line):
                            count = 2
                            continue
                        else:
                            new_iet_conf_txt.append(line)

                    iet_conf_text.seek(0)
                    iet_conf_text.truncate(0)
                    iet_conf_text.writelines(new_iet_conf_txt)
                finally:
                    iet_conf_text.close()

    def _new_target(self, name, tid, **kwargs):
        self._run('--op', 'new',
                  '--tid=%s' % tid,
                  '--params', 'Name=%s' % name,
                  **kwargs)

    def _delete_target(self, tid, **kwargs):
        self._run('--op', 'delete',
                  '--tid=%s' % tid,
                  **kwargs)

    def show_target(self, tid, iqn=None, **kwargs):
        self._run('--op', 'show',
                  '--tid=%s' % tid,
                  **kwargs)

    def _new_logicalunit(self, tid, lun, path, **kwargs):
        self._run('--op', 'new',
                  '--tid=%s' % tid,
                  '--lun=%d' % lun,
                  '--params', 'Path=%s,Type=%s' % (path, self._iotype(path)),
                  **kwargs)

    def _delete_logicalunit(self, tid, lun, **kwargs):
        self._run('--op', 'delete',
                  '--tid=%s' % tid,
                  '--lun=%d' % lun,
                  **kwargs)

    def _new_auth(self, tid, type, username, password, **kwargs):
        self._run('--op', 'new',
                  '--tid=%s' % tid,
                  '--user',
                  '--params=%s=%s,Password=%s' % (type, username, password),
                  **kwargs)


class FakeIscsiHelper(object):

    def __init__(self):
        self.tid = 1

    def set_execute(self, execute):
        self._execute = execute

    def create_iscsi_target(self, *args, **kwargs):
        self.tid += 1
        return self.tid


class LioAdm(TargetAdmin):
    """iSCSI target administration for LIO using python-rtslib."""
    def __init__(self, root_helper, execute=putils.execute):
        super(LioAdm, self).__init__('rtstool', root_helper, execute)

        try:
            self._execute('rtstool', 'verify')
        except (OSError, putils.ProcessExecutionError):
            LOG.error(_('rtstool is not installed correctly'))
            raise

    def _get_target(self, iqn):
        (out, err) = self._execute('rtstool',
                                   'get-targets',
                                   run_as_root=True)
        lines = out.split('\n')
        for line in lines:
            if iqn in line:
                return line

        return None

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):
        # tid and lun are not used

        vol_id = name.split(':')[1]

        LOG.info(_('Creating iscsi_target for volume: %s') % vol_id)

        # rtstool requires chap_auth, but unit tests don't provide it
        chap_auth_userid = 'test_id'
        chap_auth_password = 'test_pass'

        if chap_auth is not None:
            (chap_auth_userid, chap_auth_password) = chap_auth.split(' ')[1:]

        extra_args = []
        if CONF.lio_initiator_iqns:
            extra_args.append(CONF.lio_initiator_iqns)

        try:
            command_args = ['rtstool',
                            'create',
                            path,
                            name,
                            chap_auth_userid,
                            chap_auth_password]
            if extra_args:
                command_args.extend(extra_args)
            self._execute(*command_args, run_as_root=True)
        except putils.ProcessExecutionError as e:
                LOG.error(_("Failed to create iscsi target for volume "
                            "id:%s.") % vol_id)
                LOG.error("%s" % str(e))

                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        iqn = '%s%s' % (CONF.iscsi_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.error(_("Failed to create iscsi target for volume "
                        "id:%s.") % vol_id)
            raise exception.NotFound()

        return tid

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_('Removing iscsi_target: %s') % vol_id)
        vol_uuid_name = vol_name
        iqn = '%s%s' % (CONF.iscsi_target_prefix, vol_uuid_name)

        try:
            self._execute('rtstool',
                          'delete',
                          iqn,
                          run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to remove iscsi target for volume "
                        "id:%s.") % vol_id)
            LOG.error("%s" % str(e))
            raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)

    def show_target(self, tid, iqn=None, **kwargs):
        if iqn is None:
            raise exception.InvalidParameterValue(
                err=_('valid iqn needed for show_target'))

        tid = self._get_target(iqn)
        if tid is None:
            raise exception.NotFound()

    def initialize_connection(self, volume, connector):
        volume_iqn = volume['provider_location'].split(' ')[1]

        (auth_method, auth_user, auth_pass) = \
            volume['provider_auth'].split(' ', 3)

        # Add initiator iqns to target ACL
        try:
            self._execute('rtstool', 'add-initiator',
                          volume_iqn,
                          auth_user,
                          auth_pass,
                          connector['initiator'],
                          run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to add initiator iqn %s to target") %
                      connector['initiator'])
            raise exception.ISCSITargetAttachFailed(volume_id=volume['id'])


def get_target_admin(root_helper):
    if CONF.iscsi_helper == 'tgtadm':
        return TgtAdm(root_helper)
    elif CONF.iscsi_helper == 'fake':
        return FakeIscsiHelper()
    elif CONF.iscsi_helper == 'lioadm':
        return LioAdm(root_helper)
    else:
        return IetAdm(root_helper)
