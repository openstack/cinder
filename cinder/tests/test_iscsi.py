
# Copyright 2011 Red Hat, Inc.
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

import os.path
import shutil
import string
import tempfile

from cinder.brick.iscsi import iscsi
from cinder import test
from cinder.volume import driver


class TargetAdminTestCase(object):

    def setUp(self):
        self.cmds = []

        self.tid = 1
        self.target_name = 'iqn.2011-09.org.foo.bar:volume-blaa'
        self.lun = 10
        self.path = '/foo'
        self.vol_id = 'blaa'
        self.vol_name = 'volume-blaa'
        self.chap_username = 'test_id'
        self.chap_password = 'test_pass'
        self.write_cache = 'off'
        self.db = {}

        self.script_template = None
        self.stubs.Set(os.path, 'isfile', lambda _: True)
        self.stubs.Set(os, 'unlink', lambda _: '')
        self.stubs.Set(iscsi.TgtAdm, '_get_target', self.fake_get_target)
        self.stubs.Set(iscsi.LioAdm, '_get_target', self.fake_get_target)
        self.stubs.Set(iscsi.LioAdm,
                       '_verify_rtstool',
                       self.fake_verify_rtstool)
        self.driver = driver.ISCSIDriver()
        self.stubs.Set(iscsi.TgtAdm, '_verify_backing_lun',
                       self.fake_verify_backing_lun)
        self.driver = driver.ISCSIDriver()
        self.flags(iscsi_target_prefix='iqn.2011-09.org.foo.bar:')
        self.persist_tempdir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup, self.persist_tempdir)

    def fake_verify_backing_lun(obj, iqn, tid):
        return True

    def fake_verify_rtstool(obj):
        pass

    def fake_get_target(obj, iqn):
        return 1

    def get_script_params(self):
        return {'tid': self.tid,
                'target_name': self.target_name,
                'lun': self.lun,
                'path': self.path,
                'username': self.chap_username,
                'password': self.chap_password}

    def get_script(self):
        return self.script_template % self.get_script_params()

    def fake_execute(self, *cmd, **kwargs):
        self.cmds.append(string.join(cmd))
        return "", None

    def clear_cmds(self):
        self.cmds = []

    def verify_config(self):
        pass

    def verify_cmds(self, cmds):
        self.assertEqual(len(cmds), len(self.cmds))
        for cmd in self.cmds:
            self.assertTrue(cmd in cmds)
        self.verify_config()

    def verify(self):
        script = self.get_script()
        cmds = []
        for line in script.split('\n'):
            if not line.strip():
                continue
            cmds.append(line)
        self.verify_cmds(cmds)

    def run_commands(self):
        target_helper = self.driver.get_target_helper(self.db)
        target_helper.set_execute(self.fake_execute)
        chap_auth = target_helper._iscsi_authentication('IncomingUser',
                                                        self.chap_username,
                                                        self.chap_password)
        target_helper.create_iscsi_target(self.target_name, self.tid,
                                          self.lun, self.path, chap_auth,
                                          write_cache=self.write_cache)
        target_helper.show_target(self.tid, iqn=self.target_name)
        target_helper.remove_iscsi_target(self.tid, self.lun, self.vol_id,
                                          self.vol_name)

    def test_target_admin(self):
        self.clear_cmds()
        self.run_commands()
        self.verify()

    def _cleanup(self, persist_tempdir):
        try:
            shutil.rmtree(persist_tempdir)
        except OSError:
            pass


class TgtAdmTestCase(test.TestCase, TargetAdminTestCase):

    def setUp(self):
        super(TgtAdmTestCase, self).setUp()
        TargetAdminTestCase.setUp(self)
        self.flags(iscsi_helper='tgtadm')
        self.flags(volumes_dir=self.persist_tempdir)
        self.script_template = "\n".join([
            'tgt-admin --update %(target_name)s',
            'tgt-admin --delete %(target_name)s',
            'tgt-admin --force '
            '--delete %(target_name)s',
            'tgtadm --lld iscsi --op show --mode target'])

    def verify_config(self):
        target_helper = self.driver.get_target_helper(self.db)
        self.assertEqual(target_helper._get_target_chap_auth(self.target_name),
                         (self.chap_username, self.chap_password))


class IetAdmTestCase(test.TestCase, TargetAdminTestCase):

    def setUp(self):
        super(IetAdmTestCase, self).setUp()
        TargetAdminTestCase.setUp(self)
        self.flags(iscsi_helper='ietadm')
        self.script_template = "\n".join([
            'ietadm --op new --tid=%(tid)s --params Name=%(target_name)s',
            'ietadm --op new --tid=%(tid)s --lun=%(lun)s '
            '--params Path=%(path)s,Type=fileio',
            'ietadm --op new --tid=%(tid)s --user '
            '--params=IncomingUser=%(username)s,Password=%(password)s',
            'ietadm --op show --tid=%(tid)s',
            'ietadm --op delete --tid=%(tid)s --lun=%(lun)s',
            'ietadm --op delete --tid=%(tid)s'])


class IetAdmBlockIOTestCase(test.TestCase, TargetAdminTestCase):

    def setUp(self):
        super(IetAdmBlockIOTestCase, self).setUp()
        TargetAdminTestCase.setUp(self)
        self.flags(iscsi_helper='ietadm')
        self.flags(iscsi_iotype='blockio')
        self.script_template = "\n".join([
            'ietadm --op new --tid=%(tid)s --params Name=%(target_name)s',
            'ietadm --op new --tid=%(tid)s --lun=%(lun)s '
            '--params Path=%(path)s,Type=blockio',
            'ietadm --op new --tid=%(tid)s --user '
            '--params=IncomingUser=%(username)s,Password=%(password)s',
            'ietadm --op show --tid=%(tid)s',
            'ietadm --op delete --tid=%(tid)s --lun=%(lun)s',
            'ietadm --op delete --tid=%(tid)s'])


class IetAdmFileIOTestCase(test.TestCase, TargetAdminTestCase):

    def setUp(self):
        super(IetAdmFileIOTestCase, self).setUp()
        TargetAdminTestCase.setUp(self)
        self.flags(iscsi_helper='ietadm')
        self.flags(iscsi_iotype='fileio')
        self.script_template = "\n".join([
            'ietadm --op new --tid=%(tid)s --params Name=%(target_name)s',
            'ietadm --op new --tid=%(tid)s --lun=%(lun)s '
            '--params Path=%(path)s,Type=fileio',
            'ietadm --op new --tid=%(tid)s --user '
            '--params=IncomingUser=%(username)s,Password=%(password)s',
            'ietadm --op show --tid=%(tid)s',
            'ietadm --op delete --tid=%(tid)s --lun=%(lun)s',
            'ietadm --op delete --tid=%(tid)s'])


class IetAdmAutoIOTestCase(test.TestCase, TargetAdminTestCase):

    def setUp(self):
        super(IetAdmAutoIOTestCase, self).setUp()
        TargetAdminTestCase.setUp(self)
        self.stubs.Set(iscsi.IetAdm, '_is_block', lambda a, b: True)
        self.flags(iscsi_helper='ietadm')
        self.flags(iscsi_iotype='auto')
        self.script_template = "\n".join([
            'ietadm --op new --tid=%(tid)s --params Name=%(target_name)s',
            'ietadm --op new --tid=%(tid)s --lun=%(lun)s '
            '--params Path=%(path)s,Type=blockio',
            'ietadm --op new --tid=%(tid)s --user '
            '--params=IncomingUser=%(username)s,Password=%(password)s',
            'ietadm --op show --tid=%(tid)s',
            'ietadm --op delete --tid=%(tid)s --lun=%(lun)s',
            'ietadm --op delete --tid=%(tid)s'])


class LioAdmTestCase(test.TestCase, TargetAdminTestCase):

    def setUp(self):
        super(LioAdmTestCase, self).setUp()
        TargetAdminTestCase.setUp(self)
        self.flags(iscsi_helper='lioadm')
        self.script_template = "\n".join([
            'cinder-rtstool create '
            '%(path)s %(target_name)s %(username)s %(password)s',
            'cinder-rtstool delete %(target_name)s'])


class ISERTgtAdmTestCase(TgtAdmTestCase):

    def setUp(self):
        super(ISERTgtAdmTestCase, self).setUp()
        self.flags(iscsi_helper='iseradm')
