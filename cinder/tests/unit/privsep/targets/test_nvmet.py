# Copyright 2022 Red Hat, Inc
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

import unittest
from unittest import mock

import ddt

from cinder import exception
from cinder.tests.unit.privsep.targets import fake_nvmet_lib
from cinder.tests.unit import test
# This must go after fake_nvmet_lib has been imported (thus the noqa)
from cinder.privsep.targets import nvmet  # noqa


@ddt.ddt
class TestSerialize(test.TestCase):
    def setUp(self):
        super().setUp()
        fake_nvmet_lib.reset_mock()

    def test_tuple(self):
        """Test serialization of a tuple."""
        instance = (1, 'string')
        res = nvmet.serialize(instance)
        self.assertEqual(('tuple', instance), res)

    @ddt.data(1, 1.1, 'string', None, [1, 2, 'string'])
    def test_others(self, instance):
        """Test normal Python instances that should not be modified."""
        res = nvmet.serialize(instance)
        self.assertEqual(instance, res)

    def test_root(self):
        instance = nvmet.Root()
        res = nvmet.serialize(instance)
        self.assertEqual(('Root', {}), res)

    def test_host(self):
        instance = nvmet.Host(nqn='_nqn')
        res = nvmet.serialize(instance)
        self.assertEqual(('Host', {'nqn': '_nqn', 'mode': 'lookup'}), res)

    def test_subsystem(self):
        instance = nvmet.Subsystem(nqn='_nqn')
        res = nvmet.serialize(instance)
        self.assertEqual(('Subsystem', {'nqn': '_nqn', 'mode': 'lookup'}), res)

    def test_namespace(self):
        subsys = nvmet.Subsystem(nqn='_nqn')
        instance = nvmet.Namespace(subsystem=subsys, nsid='_nsid')
        res = nvmet.serialize(instance)
        # Subsystem is a recursive serialization
        expected = (
            'Namespace', {'subsystem': ('Subsystem', {'nqn': '_nqn',
                                                      'mode': 'lookup'}),
                          'nsid': '_nsid',
                          'mode': 'lookup'})
        self.assertEqual(expected, res)

    def test_port(self):
        instance = nvmet.Port(portid='_portid')
        res = nvmet.serialize(instance)
        expected = ('Port', {'portid': '_portid', 'mode': 'lookup'})
        self.assertEqual(expected, res)

    def test_Referral(self):
        port = nvmet.Port(portid='_portid')
        # name is a Mock attribute, so we'll use it as instance.name
        instance = nvmet.Referral(port=port, name='_name')
        res = nvmet.serialize(instance)
        # Port is a recursive serialization
        expected = (
            'Referral', {'port': ('Port', {'portid': '_portid',
                                           'mode': 'lookup'}),
                         'name': instance.name,
                         'mode': 'lookup'})
        self.assertEqual(expected, res)

    def test_ANAGroup(self):
        port = nvmet.Port(portid='_portid')
        instance = nvmet.ANAGroup(port=port, grpid='_grpid')
        res = nvmet.serialize(instance)
        expected = (
            'ANAGroup', {'port': ('Port', {'portid': '_portid',
                                           'mode': 'lookup'}),
                         'grpid': '_grpid',
                         'mode': 'lookup'})
        self.assertEqual(expected, res)


@ddt.ddt
class TestDeserialize(test.TestCase):
    def test_deserialize_tuple(self):
        """Test serialization of a tuple."""
        expected = (1, 'string')
        data = ('tuple', expected)
        res = nvmet.deserialize(data)
        self.assertEqual(expected, res)

    @ddt.data(1, 1.1, 'string', None, [1, 2, 'string'])
    def test_deserialize_others(self, data):
        """Test normal Python instances that should not be modified."""
        res = nvmet.deserialize(data)
        self.assertEqual(data, res)

    def test_deserialize_root(self):
        data = ('Root', {})
        res = nvmet.deserialize(data)
        self.assertIsInstance(res, nvmet.nvmet.Root)

    def test_deserialize_host(self):
        data = ('Host', {'nqn': '_nqn', 'mode': 'lookup'})
        host = nvmet.deserialize(data)
        self.assertIsInstance(host, nvmet.nvmet.Host)
        self.assertEqual('_nqn', host.nqn)
        self.assertEqual('lookup', host.mode)

    def test_deserialize_subsystem(self):
        data = ('Subsystem', {'nqn': '_nqn', 'mode': 'lookup'})
        subsys = nvmet.deserialize(data)
        self.assertIsInstance(subsys, nvmet.nvmet.Subsystem)
        self.assertEqual('_nqn', subsys.nqn)
        self.assertEqual('lookup', subsys.mode)

    def test_deserialize_namespace(self):
        data = ('Namespace', {'subsystem': ('Subsystem', {'nqn': '_nqn',
                                                          'mode': 'lookup'}),
                              'nsid': '_nsid',
                              'mode': 'lookup'})

        ns = nvmet.deserialize(data)
        self.assertIsInstance(ns, nvmet.nvmet.Namespace)
        self.assertEqual('_nsid', ns.nsid)
        self.assertEqual('lookup', ns.mode)
        self.assertIsInstance(ns.subsystem, nvmet.nvmet.Subsystem)
        self.assertEqual('_nqn', ns.subsystem.nqn)
        self.assertEqual('lookup', ns.subsystem.mode)

    def test_deserialize_port(self):
        data = ('Port', {'portid': '_portid', 'mode': 'lookup'})
        port = nvmet.deserialize(data)
        self.assertIsInstance(port, nvmet.nvmet.Port)
        self.assertEqual('_portid', port.portid)
        self.assertEqual('lookup', port.mode)

    def test_deserialize_Referral(self):
        data = ('Referral', {'port': ('Port', {'portid': '_portid',
                                               'mode': 'lookup'}),
                             'name': '1',
                             'mode': 'lookup'})
        ref = nvmet.deserialize(data)

        self.assertIsInstance(ref, nvmet.nvmet.Referral)
        self.assertEqual('1', ref._mock_name)  # Because name is used by Mock
        self.assertEqual('lookup', ref.mode)
        self.assertIsInstance(ref.port, nvmet.nvmet.Port)
        self.assertEqual('_portid', ref.port.portid)
        self.assertEqual('lookup', ref.port.mode)

    def test_deserialize_ANAGroup(self):
        data = ('ANAGroup', {'port': ('Port', {'portid': '_portid',
                                               'mode': 'lookup'}),
                             'grpid': '_grpid',
                             'mode': 'lookup'})
        ana = nvmet.deserialize(data)

        self.assertIsInstance(ana, nvmet.nvmet.ANAGroup)
        self.assertEqual('_grpid', ana.grpid)
        self.assertEqual('lookup', ana.mode)
        self.assertIsInstance(ana.port, nvmet.nvmet.Port)
        self.assertEqual('_portid', ana.port.portid)
        self.assertEqual('lookup', ana.port.mode)

    @mock.patch.object(nvmet, 'deserialize')
    def test_deserialize_params(self, mock_deserialize):
        mock_deserialize.side_effect = [11, 22, 33, 55, 77]
        args = [1, 2, 3]
        kwargs = {'4': 5, '6': 7}

        res_args, res_kwargs = nvmet.deserialize_params(args, kwargs)

        self.assertEqual(5, mock_deserialize.call_count)
        mock_deserialize.assert_has_calls((mock.call(1),
                                           mock.call(2),
                                           mock.call(3),
                                           mock.call(5),
                                           mock.call(7)))
        self.assertEqual([11, 22, 33], res_args)
        self.assertEqual({'4': 55, '6': 77}, res_kwargs)


class TestPrivsep(test.TestCase):
    @mock.patch.object(nvmet.LOG, 'error')
    def test__nvmet_setup_failure(self, mock_log):
        self.assertRaises(exception.CinderException,
                          nvmet._nvmet_setup_failure, mock.sentinel.message)
        mock_log.assert_called_once_with(mock.sentinel.message)

    @mock.patch.object(nvmet, '_privsep_setup')
    def test_privsep_setup(self, mock_setup):
        args = [mock.sentinel.arg1, mock.sentinel.arg2]
        kwargs = {'kwarg1': mock.sentinel.kwarg1}

        res = nvmet.privsep_setup('MyClass', err_func=None, *args, **kwargs)

        mock_setup.assert_called_once_with('MyClass', *args, **kwargs)
        self.assertEqual(mock_setup.return_value, res)

    @mock.patch.object(nvmet, '_privsep_setup')
    def test_privsep_setup_err_func_as_arg_none(self, mock_setup):
        exc = exception.CinderException('ouch')
        mock_setup.side_effect = exc
        args = [mock.sentinel.arg1, mock.sentinel.arg2, None]
        kwargs = {'kwarg1': mock.sentinel.kwarg1}

        # NOTE: testtools.TestCase were Cinder's tests inherit from masks the
        # unittest's assertRaises that supports context manager usage, so we
        # address it directly.
        with unittest.TestCase.assertRaises(self,
                                            exception.CinderException) as cm:
            nvmet.privsep_setup('MyClass', *args, **kwargs)

        self.assertEqual(exc, cm.exception)
        mock_setup.assert_called_once_with('MyClass', *args[:-1], **kwargs)

    @mock.patch.object(nvmet, '_privsep_setup')
    def test_privsep_setup_err_func_as_arg(self, mock_setup):
        def err_func(msg):
            raise exception.VolumeDriverException()

        mock_setup.side_effect = exception.CinderException('ouch')
        args = [mock.sentinel.arg1, mock.sentinel.arg2, err_func]

        self.assertRaises(exception.VolumeDriverException,
                          nvmet.privsep_setup, 'MyClass', *args)
        mock_setup.assert_called_once_with('MyClass', *args[:-1])

    # We mock the privsep context mode to fake that we are not the client
    @mock.patch('cinder.privsep.sys_admin_pctxt.client_mode', False)
    @mock.patch.object(nvmet, 'deserialize_params')
    @mock.patch.object(nvmet.nvmet, 'MyClass')
    def test__privsep_setup(self, mock_class, mock_deserialize):
        args = (1, 2, 3)
        kwargs = {'4': 5, '6': 7}
        deserialized_args = (11, 22, 33)
        deserialized_kwargs = {'4': 55, '6': 77}

        expected_args = deserialized_args[:]
        expected_kwargs = deserialized_kwargs.copy()
        expected_kwargs['err_func'] = nvmet._nvmet_setup_failure

        mock_deserialize.return_value = (deserialized_args,
                                         deserialized_kwargs)

        res = nvmet._privsep_setup('MyClass', *args, **kwargs)

        mock_deserialize.assert_called_once_with(args, kwargs)
        mock_class.setup.assert_called_once_with(*expected_args,
                                                 **expected_kwargs)
        self.assertEqual(mock_class.setup.return_value, res)

    # We mock the privsep context mode to fake that we are not the client
    @mock.patch('cinder.privsep.sys_admin_pctxt.client_mode', False)
    @mock.patch.object(nvmet, 'deserialize')
    @mock.patch.object(nvmet, 'deserialize_params')
    def test_do_privsep_call(self, mock_deserialize_params, mock_deserialize):
        args = (1, 2, 3)
        kwargs = {'4': 5, '6': 7}
        deserialized_args = (11, 22, 33)
        deserialized_kwargs = {'4': 55, '6': 77}

        mock_deserialize_params.return_value = (deserialized_args,
                                                deserialized_kwargs)

        res = nvmet.do_privsep_call(mock.sentinel.instance,
                                    'method_name',
                                    *args, **kwargs)
        mock_deserialize.assert_called_once_with(mock.sentinel.instance)
        mock_deserialize_params.assert_called_once_with(args, kwargs)

        mock_method = mock_deserialize.return_value.method_name
        mock_method.assert_called_once_with(*deserialized_args,
                                            **deserialized_kwargs)
        self.assertEqual(mock_method.return_value, res)


@ddt.ddt
class TestNvmetClasses(test.TestCase):
    @ddt.data('Host', 'Referral', 'ANAGroup')
    def test_same_classes(self, cls_name):
        self.assertEqual(getattr(nvmet, cls_name),
                         getattr(nvmet.nvmet, cls_name))

    def test_subsystem_init(self):
        subsys = nvmet.Subsystem('nqn')
        self.assertIsInstance(subsys, nvmet.nvmet.Subsystem)
        self.assertIsInstance(subsys, nvmet.Subsystem)
        self.assertEqual('nqn', subsys.nqn)
        self.assertEqual('lookup', subsys.mode)

    @mock.patch.object(nvmet, 'privsep_setup')
    def test_subsystem_setup(self, mock_setup):
        nvmet.Subsystem.setup(mock.sentinel.t, mock.sentinel.err_func)
        mock_setup.assert_called_once_with('Subsystem', mock.sentinel.t,
                                           mock.sentinel.err_func)

    @mock.patch.object(nvmet, 'privsep_setup')
    def test_subsystem_setup_no_err_func(self, mock_setup):
        nvmet.Subsystem.setup(mock.sentinel.t)
        mock_setup.assert_called_once_with('Subsystem', mock.sentinel.t, None)

    @mock.patch.object(nvmet, 'serialize')
    @mock.patch.object(nvmet, 'do_privsep_call')
    def test_subsystem_delete(self, mock_privsep, mock_serialize):
        subsys = nvmet.Subsystem('nqn')
        subsys.delete()
        mock_serialize.assert_called_once_with(subsys)
        mock_privsep.assert_called_once_with(mock_serialize.return_value,
                                             'delete')

    @mock.patch('os.listdir',
                return_value=['/path/namespaces/1', '/path/namespaces/2'])
    @mock.patch.object(nvmet, 'Namespace')
    def test_subsystem_namespaces(self, mock_nss, mock_listdir):
        subsys = nvmet.Subsystem(mock.sentinel.nqn)
        subsys.path = '/path'  # Set by the parent nvmet library Root class

        res = list(subsys.namespaces)

        self.assertEqual([mock_nss.return_value, mock_nss.return_value], res)

        mock_listdir.assert_called_once_with('/path/namespaces/')
        self.assertEqual(2, mock_nss.call_count)
        mock_nss.assert_has_calls((mock.call(subsys, '1'),
                                   mock.call(subsys, '2')))

    def test_port_init(self):
        port = nvmet.Port('portid')
        self.assertIsInstance(port, nvmet.nvmet.Port)
        self.assertIsInstance(port, nvmet.Port)
        self.assertEqual('portid', port.portid)
        self.assertEqual('lookup', port.mode)

    @mock.patch.object(nvmet, 'serialize')
    @mock.patch.object(nvmet, 'privsep_setup')
    def test_port_setup(self, mock_setup, mock_serialize):
        nvmet.Port.setup(mock.sentinel.root, mock.sentinel.n,
                         mock.sentinel.err_func)
        mock_serialize.assert_called_once_with(mock.sentinel.root)
        mock_setup.assert_called_once_with('Port', mock_serialize.return_value,
                                           mock.sentinel.n,
                                           mock.sentinel.err_func)

    @mock.patch.object(nvmet, 'serialize')
    @mock.patch.object(nvmet, 'privsep_setup')
    def test_port_setup_no_err_func(self, mock_setup, mock_serialize):
        nvmet.Port.setup(mock.sentinel.root, mock.sentinel.n)
        mock_serialize.assert_called_once_with(mock.sentinel.root)
        mock_setup.assert_called_once_with('Port', mock_serialize.return_value,
                                           mock.sentinel.n, None)

    @mock.patch.object(nvmet, 'serialize')
    @mock.patch.object(nvmet, 'do_privsep_call')
    def test_port_add_subsystem(self, mock_privsep, mock_serialize):
        port = nvmet.Port('portid')
        port.add_subsystem(mock.sentinel.nqn)
        mock_serialize.assert_called_once_with(port)
        mock_privsep.assert_called_once_with(mock_serialize.return_value,
                                             'add_subsystem',
                                             mock.sentinel.nqn)

    @mock.patch.object(nvmet, 'serialize')
    @mock.patch.object(nvmet, 'do_privsep_call')
    def test_port_remove_subsystem(self, mock_privsep, mock_serialize):
        port = nvmet.Port('portid')
        port.remove_subsystem(mock.sentinel.nqn)
        mock_serialize.assert_called_once_with(port)
        mock_privsep.assert_called_once_with(mock_serialize.return_value,
                                             'remove_subsystem',
                                             mock.sentinel.nqn)

    @mock.patch.object(nvmet, 'serialize')
    @mock.patch.object(nvmet, 'do_privsep_call')
    def test_port_delete(self, mock_privsep, mock_serialize):
        port = nvmet.Port('portid')
        port.delete()
        mock_serialize.assert_called_once_with(port)
        mock_privsep.assert_called_once_with(mock_serialize.return_value,
                                             'delete')

    @mock.patch('os.listdir', return_value=['/path/ports/1', '/path/ports/2'])
    @mock.patch.object(nvmet, 'Port')
    def test_root_ports(self, mock_port, mock_listdir):
        r = nvmet.Root()
        r.path = '/path'  # This is set by the parent nvmet library Root class

        res = list(r.ports)

        self.assertEqual([mock_port.return_value, mock_port.return_value], res)

        mock_listdir.assert_called_once_with('/path/ports/')
        self.assertEqual(2, mock_port.call_count)
        mock_port.assert_has_calls((mock.call('1'), mock.call('2')))

    def test_namespace_init(self):
        ns = nvmet.Namespace('subsystem', 'nsid')
        self.assertIsInstance(ns, nvmet.nvmet.Namespace)
        self.assertIsInstance(ns, nvmet.Namespace)
        self.assertEqual('subsystem', ns.subsystem)
        self.assertEqual('nsid', ns.nsid)
        self.assertEqual('lookup', ns.mode)

    @mock.patch.object(nvmet, 'serialize')
    @mock.patch.object(nvmet, 'privsep_setup')
    def test_namespace_setup(self, mock_setup, mock_serialize):
        nvmet.Namespace.setup(mock.sentinel.subsys,
                              mock.sentinel.n)
        mock_serialize.assert_called_once_with(mock.sentinel.subsys)
        mock_setup.assert_called_once_with('Namespace',
                                           mock_serialize.return_value,
                                           mock.sentinel.n, None)

    @mock.patch.object(nvmet, 'serialize')
    @mock.patch.object(nvmet, 'do_privsep_call')
    def test_namespace_delete(self, mock_privsep, mock_serialize):
        ns = nvmet.Namespace('subsystem', 'nsid')
        ns.delete()
        mock_serialize.assert_called_once_with(ns)
        mock_privsep.assert_called_once_with(mock_serialize.return_value,
                                             'delete')
