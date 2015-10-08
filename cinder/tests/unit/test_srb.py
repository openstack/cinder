# Copyright (c) 2014 Scality
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

"""Unit tests for the Scality Rest Block Volume Driver."""

import mock
from oslo_concurrency import processutils
from oslo_utils import units
import six

from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit.brick import test_brick_lvm
from cinder.volume import configuration as conf
from cinder.volume.drivers import srb


class SRBLvmTestCase(test_brick_lvm.BrickLvmTestCase):
    def setUp(self):
        super(SRBLvmTestCase, self).setUp()

        self.vg = srb.LVM(self.configuration.volume_group_name,
                          'sudo',
                          False, None,
                          'default',
                          self.fake_execute)

    def fake_execute(self, *cmd, **kwargs):
        try:
            return super(SRBLvmTestCase, self).fake_execute(*cmd, **kwargs)
        except AssertionError:
            pass

        cmd_string = ', '.join(cmd)

        if 'vgremove, -f, ' in cmd_string:
            pass
        elif 'pvresize, ' in cmd_string:
            pass
        elif 'lvextend, ' in cmd_string:
            pass
        elif 'lvchange, ' in cmd_string:
            pass
        else:
            raise AssertionError('unexpected command called: %s' % cmd_string)

    def test_activate_vg(self):
        with mock.patch.object(self.vg, '_execute') as executor:
            self.vg.activate_vg()
            executor.assert_called_once_with(
                'vgchange', '-ay',
                self.configuration.volume_group_name,
                root_helper=self.vg._root_helper,
                run_as_root=True)

    def test_deactivate_vg(self):
        with mock.patch.object(self.vg, '_execute') as executor:
            self.vg.deactivate_vg()
            executor.assert_called_once_with(
                'vgchange', '-an',
                self.configuration.volume_group_name,
                root_helper=self.vg._root_helper,
                run_as_root=True)

    def test_destroy_vg(self):
        with mock.patch.object(self.vg, '_execute') as executor:
            self.vg.destroy_vg()
            executor.assert_called_once_with(
                'vgremove', '-f',
                self.configuration.volume_group_name,
                root_helper=self.vg._root_helper,
                run_as_root=True)

    def test_pv_resize(self):
        with mock.patch.object(self.vg, '_execute') as executor:
            self.vg.pv_resize('fake-pv', '50G')
            executor.assert_called_once_with(
                'pvresize',
                '--setphysicalvolumesize',
                '50G', 'fake-pv',
                root_helper=self.vg._root_helper,
                run_as_root=True)

    def test_extend_thin_pool_nothin(self):
        with mock.patch.object(self.vg, '_execute') as executor:
            executor.side_effect = AssertionError
            thin_calc =\
                mock.MagicMock(
                    side_effect=
                    Exception('Unexpected call to _calculate_thin_pool_size'))
            self.vg._calculate_thin_pool_size = thin_calc
            self.vg.extend_thin_pool()

    def test_extend_thin_pool_thin(self):
        self.stubs.Set(processutils, 'execute', self.fake_execute)
        self.thin_vg = srb.LVM(self.configuration.volume_group_name,
                               'sudo',
                               False, None,
                               'thin',
                               self.fake_execute)
        self.assertTrue(self.thin_vg.supports_thin_provisioning('sudo'))
        self.thin_vg.update_volume_group_info = mock.MagicMock()
        with mock.patch('oslo_concurrency.processutils.execute'):
            executor = mock.MagicMock()
            self.thin_vg._execute = executor
            self.thin_vg.extend_thin_pool()
            executor.assert_called_once_with('lvextend',
                                             '-L', '9.5g',
                                             'fake-vg/fake-vg-pool',
                                             root_helper=self.vg._root_helper,
                                             run_as_root=True)
            self.thin_vg.update_volume_group_info.assert_called_once_with()


class SRBRetryTestCase(test.TestCase):

    def __init__(self, *args, **kwargs):
        super(SRBRetryTestCase, self).__init__(*args, **kwargs)
        self.attempts = 0

    def setUp(self):
        super(SRBRetryTestCase, self).setUp()
        self.attempts = 0

    def test_retry_no_failure(self):
        expected_attempts = 1

        @srb.retry(exceptions=(), count=expected_attempts)
        def _try_failing(self):
            self.attempts = self.attempts + 1
            return True

        ret = _try_failing(self)

        self.assertTrue(ret)
        self.assertEqual(expected_attempts, self.attempts)

    def test_retry_fail_by_exception(self):
        expected_attempts = 2
        ret = None

        @srb.retry(count=expected_attempts,
                   exceptions=(processutils.ProcessExecutionError))
        def _try_failing(self):
            self.attempts = self.attempts + 1
            raise processutils.ProcessExecutionError("Fail everytime")

        try:
            ret = _try_failing(self)
        except processutils.ProcessExecutionError:
            pass

        self.assertIsNone(ret)
        self.assertEqual(expected_attempts, self.attempts)

    def test_retry_fail_and_succeed_mixed(self):

        @srb.retry(count=4, exceptions=(Exception),
                   sleep_mechanism=srb.retry.SLEEP_NONE)
        def _try_failing(self):
            attempted = self.attempts
            self.attempts = self.attempts + 1
            if attempted == 0:
                raise IOError(0, 'Oops')
            if attempted == 1:
                raise Exception("Second try shall except")
            if attempted == 2:
                assert False
            return 34

        ret = _try_failing(self)

        self.assertEqual(34, ret)
        self.assertEqual(4, self.attempts)


class TestHandleProcessExecutionError(test.TestCase):
    def test_no_exception(self):
        with srb.handle_process_execution_error(
                message='', info_message='', reraise=True):
            pass

    def test_other_exception(self):
        def f():
            with srb.handle_process_execution_error(
                    message='', info_message='', reraise=True):
                1 / 0

        self.assertRaises(ZeroDivisionError, f)

    def test_reraise_true(self):
        def f():
            with srb.handle_process_execution_error(
                    message='', info_message='', reraise=True):
                raise processutils.ProcessExecutionError(description='Oops')

        self.assertRaisesRegex(processutils.ProcessExecutionError,
                               r'^Oops', f)

    def test_reraise_false(self):
        with srb.handle_process_execution_error(
                message='', info_message='', reraise=False):
            raise processutils.ProcessExecutionError(description='Oops')

    def test_reraise_exception(self):
        def f():
            with srb.handle_process_execution_error(
                    message='', info_message='', reraise=RuntimeError('Oops')):
                raise processutils.ProcessExecutionError

        self.assertRaisesRegex(RuntimeError, r'^Oops', f)


class SRBDriverTestCase(test.TestCase):
    """Test case for the Scality Rest Block driver."""

    def __init__(self, *args, **kwargs):
        super(SRBDriverTestCase, self).__init__(*args, **kwargs)
        self._urls = []
        self._volumes = {
            "fake-old-volume": {
                "name": "fake-old-volume",
                "size": 4 * units.Gi,
                "vgs": {
                    "fake-old-volume": {
                        "lvs": {"vol1": 4 * units.Gi},
                        "snaps": ["snap1", "snap2", "snap3"],
                    },
                },
            },
            "volume-extend": {
                "name": "volume-extend",
                "size": 4 * units.Gi,
                "vgs": {
                    "volume-extend": {
                        "lvs": {"volume-extend-pool": 0.95 * 4 * units.Gi,
                                "volume-extend": 4 * units.Gi},
                        "snaps": [],
                    },
                },
            },
            "volume-SnapBase": {
                "name": "volume-SnapBase",
                "size": 4 * units.Gi,
                "vgs": {
                    "volume-SnapBase": {
                        "lvs": {"volume-SnapBase-pool": 0.95 * 4 * units.Gi,
                                "volume-SnapBase": 4 * units.Gi},
                        "snaps": ['snapshot-SnappedBase', 'snapshot-delSnap'],
                    },
                },
            },
        }

    @staticmethod
    def _convert_size(s):
        if isinstance(s, six.integer_types):
            return s

        try:
            return int(s)
        except ValueError:
            pass

        conv_map = {
            'g': units.Gi,
            'G': units.Gi,
            'm': units.Mi,
            'M': units.Mi,
            'k': units.Ki,
            'K': units.Ki,
        }

        if s[-1] in conv_map:
            return int(s[:-1]) * conv_map[s[-1]]

        raise ValueError('Unknown size: %r' % s)

    def _fake_add_urls(self):
        def check(cmd_string):
            return 'tee, /sys/class/srb/add_urls' in cmd_string

        def act(cmd):
            self._urls.append(cmd[2])

        return check, act

    def _fake_create(self):
        def check(cmd_string):
            return 'tee, /sys/class/srb/create' in cmd_string

        def act(cmd):
            volname = cmd[2].split()[0]
            volsize = cmd[2].split()[1]
            self._volumes[volname] = {
                "name": volname,
                "size": self._convert_size(volsize),
                "vgs": {
                },
            }

        return check, act

    def _fake_destroy(self):
        def check(cmd_string):
            return 'tee, /sys/class/srb/destroy' in cmd_string

        def act(cmd):
            volname = cmd[2]
            del self._volumes[volname]

        return check, act

    def _fake_extend(self):
        def check(cmd_string):
            return 'tee, /sys/class/srb/extend' in cmd_string

        def act(cmd):
            volname = cmd[2].split()[0]
            volsize = cmd[2].split()[1]
            self._volumes[volname]["size"] = self._convert_size(volsize)

        return check, act

    def _fake_attach(self):
        def check(cmd_string):
            return 'tee, /sys/class/srb/attach' in cmd_string

        def act(_):
            pass

        return check, act

    def _fake_detach(self):
        def check(cmd_string):
            return 'tee, /sys/class/srb/detach' in cmd_string

        def act(_):
            pass

        return check, act

    def _fake_vg_list(self):
        def check(cmd_string):
            return 'env, LC_ALL=C, vgs, --noheadings, -o, name' in cmd_string

        def act(cmd):
            # vg exists
            data = "  fake-outer-vg\n"
            for vname in self._volumes:
                vol = self._volumes[vname]
                for vgname in vol['vgs']:
                    data += "  " + vgname + "\n"

            return data

        return check, act

    def _fake_thinpool_free_space(self):
        def check(cmd_string):
            return 'env, LC_ALL=C, lvs, --noheadings, --unit=g, '\
                '-o, size,data_percent, --separator, :, --nosuffix'\
                in cmd_string

        def act(cmd):
            data = ''

            groupname, poolname = cmd[10].split('/')[2:4]
            for vname in self._volumes:
                vol = self._volumes[vname]
                for vgname in vol['vgs']:
                    if vgname != groupname:
                        continue
                    vg = vol['vgs'][vgname]
                    for lvname in vg['lvs']:
                        if poolname != lvname:
                            continue
                        lv_size = vg['lvs'][lvname]
                        data += "  %.2f:0.00\n" % (lv_size / units.Gi)

            return data

        return check, act

    def _fake_vgs_version(self):
        def check(cmd_string):
            return 'env, LC_ALL=C, vgs, --version' in cmd_string

        def act(cmd):
            return "  LVM version:     2.02.95(2) (2012-03-06)\n"

        return check, act

    def _fake_get_all_volumes(self):
        def check(cmd_string):
            return 'env, LC_ALL=C, lvs, --noheadings, --unit=g, ' \
                '-o, vg_name,name,size, --nosuffix' in cmd_string

        def act(cmd):
            # get_all_volumes
            data = "  fake-outer-vg fake-1 1.00g\n"
            for vname in self._volumes:
                vol = self._volumes[vname]
                for vgname in vol['vgs']:
                    vg = vol['vgs'][vgname]
                    for lvname in vg['lvs']:
                        lv_size = vg['lvs'][lvname]
                        data += "  %s %s %.2fg\n" %\
                            (vgname, lvname, lv_size)

            return data

        return check, act

    def _fake_get_all_physical_volumes(self):
        def check(cmd_string):
            return 'env, LC_ALL=C, pvs, --noheadings, --unit=g, ' \
                '-o, vg_name,name,size,free, --separator, |, ' \
                '--nosuffix' in cmd_string

        def act(cmd):
            data = "  fake-outer-vg|/dev/fake1|10.00|1.00\n"
            for vname in self._volumes:
                vol = self._volumes[vname]
                for vgname in vol['vgs']:
                    vg = vol['vgs'][vgname]
                    for lvname in vg['lvs']:
                        lv_size = vg['lvs'][lvname]
                        data += "  %s|/dev/srb/%s/device|%.2f|%.2f\n" %\
                            (vgname, vol['name'],
                             lv_size / units.Gi, lv_size / units.Gi)

            return data

        return check, act

    def _fake_get_all_volume_groups(self):
        def check(cmd_string):
            return 'env, LC_ALL=C, vgs, --noheadings, --unit=g, ' \
                '-o, name,size,free,lv_count,uuid, --separator, :, ' \
                '--nosuffix' in cmd_string

        def act(cmd):
            data = ''

            search_vgname = None
            if len(cmd) == 11:
                search_vgname = cmd[10]
            # get_all_volume_groups
            if search_vgname is None:
                data = "  fake-outer-vg:10.00:10.00:0:"\
                       "kVxztV-dKpG-Rz7E-xtKY-jeju-QsYU-SLG6Z1\n"
            for vname in self._volumes:
                vol = self._volumes[vname]
                for vgname in vol['vgs']:
                    if search_vgname is None or search_vgname == vgname:
                        vg = vol['vgs'][vgname]
                        data += "  %s:%.2f:%.2f:%i:%s\n" %\
                            (vgname,
                             vol['size'] / units.Gi, vol['size'] / units.Gi,
                             len(vg['lvs']) + len(vg['snaps']), vgname)

            return data

        return check, act

    def _fake_udevadm_settle(self):
        def check(cmd_string):
            return 'udevadm, settle, ' in cmd_string

        def act(_):
            pass

        return check, act

    def _fake_vgcreate(self):
        def check(cmd_string):
            return 'vgcreate, ' in cmd_string

        def act(cmd):
            volname = "volume-%s" % (cmd[2].split('/')[2].split('-')[1])
            vgname = cmd[1]
            self._volumes[volname]['vgs'][vgname] = {
                "lvs": {},
                "snaps": []
            }

        return check, act

    def _fake_vgremove(self):
        def check(cmd_string):
            return 'vgremove, -f, ' in cmd_string

        def act(cmd):
            volname = cmd[2]
            del self._volumes[volname]['vgs'][volname]

        return check, act

    def _fake_vgchange_ay(self):
        def check(cmd_string):
            return 'vgchange, -ay, ' in cmd_string

        def act(_):
            pass

        return check, act

    def _fake_vgchange_an(self):
        def check(cmd_string):
            return 'vgchange, -an, ' in cmd_string

        def act(_):
            pass

        return check, act

    def _fake_lvcreate_T_L(self):
        def check(cmd_string):
            return 'lvcreate, -T, -L, ' in cmd_string

        def act(cmd):
            vgname = cmd[4].split('/')[0]
            lvname = cmd[4].split('/')[1]
            if cmd[3][-1] == 'g':
                lv_size = int(float(cmd[3][0:-1]) * units.Gi)
            elif cmd[3][-1] == 'B':
                lv_size = int(cmd[3][0:-1])
            else:
                lv_size = int(cmd[3])
            self._volumes[vgname]['vgs'][vgname]['lvs'][lvname] = lv_size

        return check, act

    def _fake_lvcreate_T_V(self):
        def check(cmd_string):
            return 'lvcreate, -T, -V, ' in cmd_string

        def act(cmd):
            cmd_string = ', '.join(cmd)

            vgname = cmd[6].split('/')[0]
            poolname = cmd[6].split('/')[1]
            lvname = cmd[5]
            if poolname not in self._volumes[vgname]['vgs'][vgname]['lvs']:
                raise AssertionError('thin-lv creation attempted before '
                                     'thin-pool creation: %s'
                                     % cmd_string)
            if cmd[3][-1] == 'g':
                lv_size = int(float(cmd[3][0:-1]) * units.Gi)
            elif cmd[3][-1] == 'B':
                lv_size = int(cmd[3][0:-1])
            else:
                lv_size = int(cmd[3])
            self._volumes[vgname]['vgs'][vgname]['lvs'][lvname] = lv_size

        return check, act

    def _fake_lvcreate_name(self):
        def check(cmd_string):
            return 'lvcreate, --name, ' in cmd_string

        def act(cmd):
            cmd_string = ', '.join(cmd)

            vgname = cmd[4].split('/')[0]
            lvname = cmd[4].split('/')[1]
            snapname = cmd[2]
            if lvname not in self._volumes[vgname]['vgs'][vgname]['lvs']:
                raise AssertionError('snap creation attempted on non-existent '
                                     'thin-lv: %s' % cmd_string)
            if snapname[1:] in self._volumes[vgname]['vgs'][vgname]['snaps']:
                raise AssertionError('snap creation attempted on existing '
                                     'snapshot: %s' % cmd_string)
            self._volumes[vgname]['vgs'][vgname]['snaps'].append(snapname[1:])

        return check, act

    def _fake_lvchange(self):
        def check(cmd_string):
            return 'lvchange, -a, y, --yes' in cmd_string or \
                   'lvchange, -a, n' in cmd_string

        def act(_):
            pass

        return check, act

    def _fake_lvremove(self):

        def check(cmd_string):
            return 'lvremove, --config, activation ' \
                '{ retry_deactivation = 1}, -f, ' in cmd_string

        def act(cmd):
            cmd_string = ', '.join(cmd)

            vgname = cmd[4].split('/')[0]
            lvname = cmd[4].split('/')[1]
            if lvname in self._volumes[vgname]['vgs'][vgname]['lvs']:
                del self._volumes[vgname]['vgs'][vgname]['lvs'][lvname]
            elif lvname in self._volumes[vgname]['vgs'][vgname]['snaps']:
                self._volumes[vgname]['vgs'][vgname]['snaps'].remove(lvname)
            else:
                raise AssertionError('Cannot delete inexistant lv or snap'
                                     'thin-lv: %s' % cmd_string)

        return check, act

    def _fake_lvdisplay(self):
        def check(cmd_string):
            return 'env, LC_ALL=C, lvdisplay, --noheading, -C, -o, Attr, ' \
                in cmd_string

        def act(cmd):
            data = ''
            cmd_string = ', '.join(cmd)

            vgname = cmd[7].split('/')[0]
            lvname = cmd[7].split('/')[1]
            if lvname not in self._volumes[vgname]['vgs'][vgname]['lvs']:
                raise AssertionError('Cannot check snaps for inexistant lv'
                                     ': %s' % cmd_string)
            if len(self._volumes[vgname]['vgs'][vgname]['snaps']):
                data = '  owi-a-\n'
            else:
                data = '  wi-a-\n'

            return data

        return check, act

    def _fake_lvextend(self):
        def check(cmd_string):
            return 'lvextend, -L, ' in cmd_string

        def act(cmd):
            cmd_string = ', '.join(cmd)
            vgname = cmd[3].split('/')[0]
            lvname = cmd[3].split('/')[1]
            if cmd[2][-1] == 'g':
                size = int(float(cmd[2][0:-1]) * units.Gi)
            elif cmd[2][-1] == 'B':
                size = int(cmd[2][0:-1])
            else:
                size = int(cmd[2])
            if vgname not in self._volumes:
                raise AssertionError('Cannot extend inexistant volume'
                                     ': %s' % cmd_string)
            if lvname not in self._volumes[vgname]['vgs'][vgname]['lvs']:
                raise AssertionError('Cannot extend inexistant lv'
                                     ': %s' % cmd_string)
            self._volumes[vgname]['vgs'][vgname]['lvs'][lvname] = size

        return check, act

    def _fake_pvresize(self):
        def check(cmd_string):
            return 'pvresize, ' in cmd_string

        def act(_):
            pass

        return check, act

    def _fake_execute(self, *cmd, **kwargs):
        # Initial version of this driver used to perform commands this way :
        # sh echo $cmd > /sys/class/srb
        # As noted in LP #1414531 this is wrong, it should be
        # tee /sys/class/srb < $cmd
        # To avoid having to rewrite every unit tests, we insert the STDIN
        # as part of the original command
        if 'process_input' in kwargs:
            cmd = cmd + (kwargs['process_input'],)
        cmd_string = ', '.join(cmd)
        ##
        #  To test behavior, we need to stub part of the brick/local_dev/lvm
        #  functions too, because we want to check the state between calls,
        #  not only if the calls were done
        ##

        handlers = [
            self._fake_add_urls(),
            self._fake_attach(),
            self._fake_create(),
            self._fake_destroy(),
            self._fake_detach(),
            self._fake_extend(),
            self._fake_get_all_physical_volumes(),
            self._fake_get_all_volume_groups(),
            self._fake_get_all_volumes(),
            self._fake_lvchange(),
            self._fake_lvcreate_T_L(),
            self._fake_lvcreate_T_V(),
            self._fake_lvcreate_name(),
            self._fake_lvdisplay(),
            self._fake_lvextend(),
            self._fake_lvremove(),
            self._fake_pvresize(),
            self._fake_thinpool_free_space(),
            self._fake_udevadm_settle(),
            self._fake_vg_list(),
            self._fake_vgchange_an(),
            self._fake_vgchange_ay(),
            self._fake_vgcreate(),
            self._fake_vgremove(),
            self._fake_vgs_version(),
        ]

        for (check, act) in handlers:
            if check(cmd_string):
                out = act(cmd)
                return (out, '')

        self.fail('Unexpected command: %s' % cmd_string)

    def _configure_driver(self):
        srb.CONF.srb_base_urls = "http://127.0.0.1/volumes"

    def setUp(self):
        super(SRBDriverTestCase, self).setUp()

        self.configuration = conf.Configuration(None)
        self._driver = srb.SRBDriver(configuration=self.configuration)
        # Stub processutils.execute for static methods
        self.stubs.Set(processutils, 'execute', self._fake_execute)
        exec_patcher = mock.patch.object(self._driver,
                                         '_execute',
                                         self._fake_execute)
        exec_patcher.start()
        self.addCleanup(exec_patcher.stop)
        self._configure_driver()

    def test_setup(self):
        """The url shall be added automatically"""
        self._driver.do_setup(None)
        self.assertEqual('http://127.0.0.1/volumes',
                         self._urls[0])
        self._driver.check_for_setup_error()

    @mock.patch.object(srb.CONF, 'srb_base_urls', "http://; evil")
    def test_setup_malformated_url(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.do_setup, None)

    def test_setup_no_config(self):
        """The driver shall not start without any url configured"""
        srb.CONF.srb_base_urls = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.do_setup, None)

    def test_volume_create(self):
        """"Test volume create.

        The volume will be added in the internal state through fake_execute.
        """
        volume = {'name': 'volume-test', 'id': 'test', 'size': 4 * units.Gi}
        old_vols = self._volumes
        updates = self._driver.create_volume(volume)
        self.assertEqual({'provider_location': volume['name']}, updates)
        new_vols = self._volumes
        old_vols['volume-test'] = {
            'name': 'volume-test',
            'size': 4 * units.Gi,
            'vgs': {
                'volume-test': {
                    'lvs': {'volume-test-pool': 0.95 * 4 * units.Gi,
                            'volume-test': 4 * units.Gi},
                    'snaps': [],
                },
            },
        }
        self.assertDictMatch(old_vols, new_vols)

    def test_volume_delete(self):
        vol = {'name': 'volume-delete', 'id': 'delete', 'size': units.Gi}

        old_vols = self._volumes
        self._volumes['volume-delete'] = {
            'name': 'volume-delete',
            'size': units.Gi,
            'vgs': {
                'volume-delete': {
                    'lvs': {'volume-delete-pool': 0.95 * units.Gi,
                            'volume-delete': units.Gi},
                    'snaps': [],
                },
            },
        }
        self._driver.delete_volume(vol)
        new_vols = self._volumes
        self.assertDictMatch(old_vols, new_vols)

    def test_volume_create_and_delete(self):
        volume = {'name': 'volume-autoDelete', 'id': 'autoDelete',
                  'size': 4 * units.Gi}
        old_vols = self._volumes
        updates = self._driver.create_volume(volume)
        self.assertEqual({'provider_location': volume['name']}, updates)
        self._driver.delete_volume(volume)
        new_vols = self._volumes
        self.assertDictMatch(old_vols, new_vols)

    def test_volume_create_cloned(self):
        with mock.patch('cinder.volume.utils.copy_volume'):
            new = {'name': 'volume-cloned', 'size': 4 * units.Gi,
                   'id': 'cloned'}
            old = {'name': 'volume-old', 'size': 4 * units.Gi, 'id': 'old'}
            old_vols = self._volumes
            self._volumes['volume-old'] = {
                'name': 'volume-old',
                'size': 4 * units.Gi,
                'vgs': {
                    'volume-old': {
                        'name': 'volume-old',
                        'lvs': {'volume-old-pool': 0.95 * 4 * units.Gi,
                                'volume-old': 4 * units.Gi},
                        'snaps': [],
                    },
                },
            }
            self._driver.create_cloned_volume(new, old)
            new_vols = self._volumes
            old_vols['volume-cloned'] = {
                'name': 'volume-cloned',
                'size': 4 * units.Gi,
                'vgs': {
                    'volume-cloned': {
                        'name': 'volume-cloned',
                        'lvs': {'volume-cloned-pool': 0.95 * 4 * units.Gi,
                                'volume-cloned': 4 * units.Gi},
                        'snaps': [],
                    },
                },
            }
            self.assertDictMatch(old_vols, new_vols)

    def test_volume_create_from_snapshot(self):
        cp_vol_patch = mock.patch('cinder.volume.utils.copy_volume')
        lv_activ_patch = mock.patch(
            'cinder.brick.local_dev.lvm.LVM.activate_lv')

        with cp_vol_patch as cp_vol, lv_activ_patch as lv_activ:
            old_vols = self._volumes
            newvol = {"name": "volume-SnapClone", "id": "SnapClone",
                      "size": 4 * units.Gi}
            srcsnap = {"name": "snapshot-SnappedBase", "id": "SnappedBase",
                       "volume_id": "SnapBase", "volume_size": 4,
                       "volume_name": "volume-SnapBase"}

            self._driver.create_volume_from_snapshot(newvol, srcsnap)

            expected_lv_activ_calls = [
                mock.call(mock.ANY, srcsnap['volume_name'] + "-pool"),
                mock.call(mock.ANY, srcsnap['name'], True)
            ]
            lv_activ.assert_has_calls(expected_lv_activ_calls, any_order=True)
            cp_vol.assert_called_with(
                '/dev/mapper/volume--SnapBase-_snapshot--SnappedBase',
                '/dev/mapper/volume--SnapClone-volume--SnapClone',
                srcsnap['volume_size'] * units.Ki,
                self._driver.configuration.volume_dd_blocksize,
                execute=self._fake_execute)

            new_vols = self._volumes
            old_vols['volume-SnapClone'] = {
                "name": 'volume-SnapClone',
                "id": 'SnapClone',
                "size": 30,
                "vgs": {
                    "name": 'volume-SnapClone',
                    "lvs": {'volume-SnapClone-pool': 0.95 * 30 * units.Gi,
                            'volume-SnapClone': 30 * units.Gi},
                    "snaps": [],
                },
            }
            self.assertDictMatch(old_vols, new_vols)

    def test_volume_snapshot_create(self):
        old_vols = self._volumes
        snap = {"name": "snapshot-SnapBase1",
                "id": "SnapBase1",
                "volume_name": "volume-SnapBase",
                "volume_id": "SnapBase",
                "volume_size": 4}
        self._driver.create_snapshot(snap)
        new_vols = self._volumes
        old_vols['volume-SnapBase']["vgs"]['volume-SnapBase']["snaps"].\
            append('snapshot-SnapBase1')
        self.assertDictMatch(old_vols, new_vols)

    def test_volume_snapshot_delete(self):
        old_vols = self._volumes
        snap = {"name": "snapshot-delSnap",
                "id": "delSnap",
                "volume_name": "volume-SnapBase",
                "volume_id": "SnapBase",
                "volume_size": 4}
        self._driver.delete_snapshot(snap)
        new_vols = self._volumes
        old_vols['volume-SnapBase']["vgs"]['volume-SnapBase']["snaps"].\
            remove(snap['name'])
        self.assertDictMatch(old_vols, new_vols)
        self.assertEqual(
            set(old_vols['volume-SnapBase']['vgs']
                ['volume-SnapBase']['snaps']),
            set(new_vols['volume-SnapBase']['vgs']
                ['volume-SnapBase']['snaps']))

    def test_volume_copy_from_image(self):
        with (mock.patch('cinder.image.image_utils.fetch_to_volume_format'))\
                as fetch:
            vol = {'name': 'volume-SnapBase', 'id': 'SnapBase',
                   'size': 5 * units.Gi}
            self._driver.copy_image_to_volume(context,
                                              vol,
                                              'image_service',
                                              'image_id')
            fetch.assert_called_once_with(context,
                                          'image_service',
                                          'image_id',
                                          self._driver._mapper_path(vol),
                                          'qcow2',
                                          self._driver.
                                          configuration.volume_dd_blocksize,
                                          size=vol['size'])

    def test_volume_copy_to_image(self):
        with mock.patch('cinder.image.image_utils.upload_volume') as upload:
            vol = {'name': 'volume-SnapBase', 'id': 'SnapBase',
                   'size': 5 * units.Gi}
            self._driver.copy_volume_to_image(context,
                                              vol,
                                              'image_service',
                                              'image_meta')
            upload.assert_called_once_with(context,
                                           'image_service',
                                           'image_meta',
                                           self._driver._mapper_path(vol))

    def test_volume_extend(self):
        vol = {'name': 'volume-extend', 'id': 'extend', 'size': 4 * units.Gi}
        new_size = 5

        self._driver.extend_volume(vol, new_size)

        new_vols = self._volumes
        self.assertEqual(srb.SRBDriver.OVER_ALLOC_RATIO * new_size * units.Gi,
                         new_vols['volume-extend']['size'])
