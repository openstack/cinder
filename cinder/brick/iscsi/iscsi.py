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
import time

from cinder.brick import exception
from cinder.brick import executor
from cinder.openstack.common import fileutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils


LOG = logging.getLogger(__name__)


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
        """Remove a iSCSI target and logical unit."""
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
    VOLUME_CONF = """
                <target %s>
                    backing-store %s
                </target>
                  """
    VOLUME_CONF_WITH_CHAP_AUTH = """
                                <target %s>
                                    backing-store %s
                                    %s
                                </target>
                                 """

    def __init__(self, root_helper, volumes_dir,
                 target_prefix='iqn.2010-10.org.openstack:',
                 execute=putils.execute):
        super(TgtAdm, self).__init__('tgtadm', root_helper, execute)

        self.iscsi_target_prefix = target_prefix
        self.volumes_dir = volumes_dir

    def _get_target(self, iqn):
        (out, err) = self._execute('tgt-admin', '--show', run_as_root=True)
        lines = out.split('\n')
        for line in lines:
            if iqn in line:
                parsed = line.split()
                tid = parsed[1]
                return tid[:-1]

        return None

    def _verify_backing_lun(self, iqn, tid):
        backing_lun = True
        capture = False
        target_info = []

        (out, err) = self._execute('tgt-admin', '--show', run_as_root=True)
        lines = out.split('\n')

        for line in lines:
            if iqn in line and "Target %s" % tid in line:
                capture = True
            if capture:
                target_info.append(line)
            if iqn not in line and 'Target ' in line:
                capture = False

        if '        LUN: 1' not in target_info:
            backing_lun = False

        return backing_lun

    def _recreate_backing_lun(self, iqn, tid, name, path):
        LOG.warning(_('Attempting recreate of backing lun...'))

        # Since we think the most common case of this is a dev busy
        # (create vol from snapshot) we're going to add a sleep here
        # this will hopefully give things enough time to stabilize
        # how long should we wait??  I have no idea, let's go big
        # and error on the side of caution

        time.sleep(10)
        try:
            (out, err) = self._execute('tgtadm', '--lld', 'iscsi',
                                       '--op', 'new', '--mode',
                                       'logicalunit', '--tid',
                                       tid, '--lun', '1', '-b',
                                       path, run_as_root=True)
            LOG.debug('StdOut from recreate backing lun: %s' % out)
            LOG.debug('StdErr from recreate backing lun: %s' % err)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to recover attempt to create "
                        "iscsi backing lun for volume "
                        "id:%(vol_id)s: %(e)s")
                      % {'vol_id': name, 'e': e})

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):
        # Note(jdg) tid and lun aren't used by TgtAdm but remain for
        # compatibility

        fileutils.ensure_tree(self.volumes_dir)

        vol_id = name.split(':')[1]
        if chap_auth is None:
            volume_conf = self.VOLUME_CONF % (name, path)
        else:
            volume_conf = self.VOLUME_CONF_WITH_CHAP_AUTH % (name,
                                                             path, chap_auth)

        LOG.info(_('Creating iscsi_target for: %s') % vol_id)
        volumes_dir = self.volumes_dir
        volume_path = os.path.join(volumes_dir, vol_id)

        f = open(volume_path, 'w+')
        f.write(volume_conf)
        f.close()
        LOG.debug(_('Created volume path %(vp)s,\n'
                    'content: %(vc)s')
                  % {'vp': volume_path, 'vc': volume_conf})

        old_persist_file = None
        old_name = kwargs.get('old_name', None)
        if old_name is not None:
            old_persist_file = os.path.join(volumes_dir, old_name)

        try:
            # with the persistent tgts we create them
            # by creating the entry in the persist file
            # and then doing an update to get the target
            # created.
            (out, err) = self._execute('tgt-admin', '--update', name,
                                       run_as_root=True)
            LOG.debug("StdOut from tgt-admin --update: %s", out)
            LOG.debug("StdErr from tgt-admin --update: %s", err)

            # Grab targets list for debug
            # Consider adding a check for lun 0 and 1 for tgtadm
            # before considering this as valid
            (out, err) = self._execute('tgtadm',
                                       '--lld',
                                       'iscsi',
                                       '--op',
                                       'show',
                                       '--mode',
                                       'target',
                                       run_as_root=True)
            LOG.debug("Targets after update: %s" % out)
        except putils.ProcessExecutionError as e:
            LOG.warning(_("Failed to create iscsi target for volume "
                        "id:%(vol_id)s: %(e)s")
                        % {'vol_id': vol_id, 'e': e})

            #Don't forget to remove the persistent file we created
            os.unlink(volume_path)
            raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        iqn = '%s%s' % (self.iscsi_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.error(_("Failed to create iscsi target for volume "
                        "id:%(vol_id)s. Please ensure your tgtd config file "
                        "contains 'include %(volumes_dir)s/*'") % {
                      'vol_id': vol_id,
                      'volumes_dir': volumes_dir, })
            raise exception.NotFound()

        # NOTE(jdg): Sometimes we have some issues with the backing lun
        # not being created, believe this is due to a device busy
        # or something related, so we're going to add some code
        # here that verifies the backing lun (lun 1) was created
        # and we'll try and recreate it if it's not there
        if not self._verify_backing_lun(iqn, tid):
            try:
                self._recreate_backing_lun(iqn, tid, name, path)
            except putils.ProcessExecutionError:
                os.unlink(volume_path)
                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

            # Finally check once more and if no go, fail and punt
            if not self._verify_backing_lun(iqn, tid):
                os.unlink(volume_path)
                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        if old_persist_file is not None and os.path.exists(old_persist_file):
            os.unlink(old_persist_file)

        return tid

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_('Removing iscsi_target for: %s') % vol_id)
        vol_uuid_file = vol_name
        volume_path = os.path.join(self.volumes_dir, vol_uuid_file)
        if not os.path.exists(volume_path):
            LOG.warning(_('Volume path %s does not exist, '
                          'nothing to remove.') % volume_path)
            return

        if os.path.isfile(volume_path):
            iqn = '%s%s' % (self.iscsi_target_prefix,
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
                      % {'vol_id': vol_id, 'e': e})
            raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)

        # NOTE(jdg): There's a bug in some versions of tgt that
        # will sometimes fail silently when using the force flag
        #    https://bugs.launchpad.net/ubuntu/+source/tgt/+bug/1305343
        # For now work-around by checking if the target was deleted,
        # if it wasn't, try again without the force.

        # This will NOT do any good for the case of mutliple sessions
        # which the force was aded for but it will however address
        # the cases pointed out in bug:
        #    https://bugs.launchpad.net/cinder/+bug/1304122
        if self._get_target(iqn):
            try:
                LOG.warning(_('Silent failure of target removal '
                              'detected, retry....'))
                self._execute('tgt-admin',
                              '--delete',
                              iqn,
                              run_as_root=True)
            except putils.ProcessExecutionError as e:
                LOG.error(_("Failed to remove iscsi target for volume "
                            "id:%(vol_id)s: %(e)s")
                          % {'vol_id': vol_id, 'e': e})
                raise exception.ISCSITargetRemoveFailed(volume_id=vol_id)

        # NOTE(jdg): This *should* be there still but incase
        # it's not we don't care, so just ignore it if was
        # somehow deleted between entry of this method
        # and here
        if os.path.exists(volume_path):
            os.unlink(volume_path)
        else:
            LOG.debug('Volume path %s not found at end, '
                      'of remove_iscsi_target.' % volume_path)

    def show_target(self, tid, iqn=None, **kwargs):
        if iqn is None:
            raise exception.InvalidParameterValue(
                err=_('valid iqn needed for show_target'))

        tid = self._get_target(iqn)
        if tid is None:
            raise exception.NotFound()


class IetAdm(TargetAdmin):
    """iSCSI target administration using ietadm."""

    def __init__(self, root_helper, iet_conf='/etc/iet/ietd.conf',
                 iscsi_iotype='fileio', execute=putils.execute):
        super(IetAdm, self).__init__('ietadm', root_helper, execute)
        self.iet_conf = iet_conf
        self.iscsi_iotype = iscsi_iotype

    def _is_block(self, path):
        mode = os.stat(path).st_mode
        return stat.S_ISBLK(mode)

    def _iotype(self, path):
        if self.iscsi_iotype == 'auto':
            return 'blockio' if self._is_block(path) else 'fileio'
        else:
            return self.iscsi_iotype

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
            putils.execute('chown', owner_uid, path,
                           root_helper=self._root_helper, run_as_root=True)
        try:
            yield
        finally:
            if orig_uid != owner_uid:
                putils.execute('chown', orig_uid, path,
                               root_helper=self._root_helper, run_as_root=True)

    def create_iscsi_target(self, name, tid, lun, path,
                            chap_auth=None, **kwargs):

        # NOTE (jdg): Address bug: 1175207
        kwargs.pop('old_name', None)

        self._new_target(name, tid, **kwargs)
        self._new_logicalunit(tid, lun, path, **kwargs)
        if chap_auth is not None:
            (type, username, password) = chap_auth.split()
            self._new_auth(tid, type, username, password, **kwargs)

        conf_file = self.iet_conf
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
                          % {'vol_id': vol_id, 'e': e})
                raise exception.ISCSITargetCreateFailed(volume_id=vol_id)
        return tid

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_('Removing iscsi_target for volume: %s') % vol_id)
        self._delete_logicalunit(tid, lun, **kwargs)
        self._delete_target(tid, **kwargs)
        vol_uuid_file = vol_name
        conf_file = self.iet_conf
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
        self._execute = None

    def set_execute(self, execute):
        self._execute = execute

    def create_iscsi_target(self, *args, **kwargs):
        self.tid += 1
        return self.tid


class LioAdm(TargetAdmin):
    """iSCSI target administration for LIO using python-rtslib."""
    def __init__(self, root_helper, lio_initiator_iqns='',
                 iscsi_target_prefix='iqn.2010-10.org.openstack:',
                 execute=putils.execute):
        super(LioAdm, self).__init__('cinder-rtstool', root_helper, execute)

        self.iscsi_target_prefix = iscsi_target_prefix
        self.lio_initiator_iqns = lio_initiator_iqns
        self._verify_rtstool()

    def _verify_rtstool(self):
        try:
            self._execute('cinder-rtstool', 'verify')
        except (OSError, putils.ProcessExecutionError):
            LOG.error(_('cinder-rtstool is not installed correctly'))
            raise

    def _get_target(self, iqn):
        (out, err) = self._execute('cinder-rtstool',
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
        if self.lio_initiator_iqns:
            extra_args.append(self.lio_initiator_iqns)

        try:
            command_args = ['cinder-rtstool',
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
            LOG.error("%s" % e)

            raise exception.ISCSITargetCreateFailed(volume_id=vol_id)

        iqn = '%s%s' % (self.iscsi_target_prefix, vol_id)
        tid = self._get_target(iqn)
        if tid is None:
            LOG.error(_("Failed to create iscsi target for volume "
                        "id:%s.") % vol_id)
            raise exception.NotFound()

        return tid

    def remove_iscsi_target(self, tid, lun, vol_id, vol_name, **kwargs):
        LOG.info(_('Removing iscsi_target: %s') % vol_id)
        vol_uuid_name = vol_name
        iqn = '%s%s' % (self.iscsi_target_prefix, vol_uuid_name)

        try:
            self._execute('cinder-rtstool',
                          'delete',
                          iqn,
                          run_as_root=True)
        except putils.ProcessExecutionError as e:
            LOG.error(_("Failed to remove iscsi target for volume "
                        "id:%s.") % vol_id)
            LOG.error("%s" % e)
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
            self._execute('cinder-rtstool', 'add-initiator',
                          volume_iqn,
                          auth_user,
                          auth_pass,
                          connector['initiator'],
                          run_as_root=True)
        except putils.ProcessExecutionError:
            LOG.error(_("Failed to add initiator iqn %s to target") %
                      connector['initiator'])
            raise exception.ISCSITargetAttachFailed(volume_id=volume['id'])


class ISERTgtAdm(TgtAdm):
    VOLUME_CONF = """
                <target %s>
                    driver iser
                    backing-store %s
                </target>
                  """
    VOLUME_CONF_WITH_CHAP_AUTH = """
                                <target %s>
                                    driver iser
                                    backing-store %s
                                    %s
                                </target>
                                 """

    def __init__(self, root_helper, volumes_dir,
                 target_prefix='iqn.2010-10.org.iser.openstack:',
                 execute=putils.execute):
        super(ISERTgtAdm, self).__init__(root_helper, volumes_dir,
                                         target_prefix, execute)
