# Copyright (c) 2016 EMC Corporation.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from unittest import mock

import six

from cinder import context
from cinder.tests.unit.consistencygroup import fake_cgsnapshot
from cinder.tests.unit.consistencygroup import fake_consistencygroup
from cinder.tests.unit import fake_constants
from cinder.tests.unit import fake_group
from cinder.tests.unit import fake_snapshot
from cinder.tests.unit import fake_volume
from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_exception as \
    lib_ex
from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_storops as \
    storops
from cinder.tests.unit.volume.drivers.dell_emc.vnx import utils
from cinder.volume.drivers.dell_emc.vnx import adapter
from cinder.volume.drivers.dell_emc.vnx import client
from cinder.volume.drivers.dell_emc.vnx import common
from cinder.volume.drivers.dell_emc.vnx import driver
from cinder.volume.drivers.dell_emc.vnx import utils as vnx_utils

SYMBOL_TYPE = '_type'
SYMBOL_PROPERTIES = '_properties'
SYMBOL_METHODS = '_methods'
SYMBOL_SIDE_EFFECT = '_side_effect'
SYMBOL_RAISE = '_raise'
SYMBOL_CONTEXT = '_context'
UUID = '_uuid'
SYMBOL_ENUM = '_enum'


def _is_driver_object(obj_body):
    return isinstance(obj_body, dict) and SYMBOL_PROPERTIES in obj_body


class DriverResourceMock(dict):
    fake_func_mapping = {}

    def __init__(self, yaml_file):
        yaml_dict = utils.load_yaml(yaml_file)
        if not isinstance(yaml_dict, dict):
            return
        for case_name, case_res in yaml_dict.items():
            if not isinstance(case_res, dict):
                continue
            self[case_name] = {}
            for obj_name, obj_body in case_res.items():
                self[case_name][obj_name] = self._parse_driver_object(obj_body)

    def _parse_driver_object(self, obj_body):
        if isinstance(obj_body, dict):
            obj_body = {k: self._parse_driver_object(v)
                        for k, v in obj_body.items()}
            if _is_driver_object(obj_body):
                return self._create_object(obj_body)
            else:
                return obj_body
        elif isinstance(obj_body, list):
            return map(self._parse_driver_object, obj_body)
        else:
            return obj_body

    def _create_object(self, obj_body):
        props = obj_body[SYMBOL_PROPERTIES]
        for prop_name, prop_value in props.items():
            if isinstance(prop_value, dict) and prop_value:
                # get the first key as the convert function
                func_name = list(prop_value.keys())[0]
                if func_name.startswith('_'):
                    func = getattr(self, func_name)
                    props[prop_name] = func(prop_value[func_name])

        if (SYMBOL_TYPE in obj_body and
                obj_body[SYMBOL_TYPE] in self.fake_func_mapping):
            return self.fake_func_mapping[obj_body[SYMBOL_TYPE]](**props)
        else:
            return props

    @staticmethod
    def _uuid(uuid_key):
        uuid_key = uuid_key.upper()
        return getattr(fake_constants, uuid_key)


def _fake_volume_wrapper(*args, **kwargs):
    expected_attrs_key = {'volume_attachment': 'volume_attachment',
                          'volume_metadata': 'metadata'}
    if 'group' in kwargs:
        expected_attrs_key['group'] = kwargs['group']

    return fake_volume.fake_volume_obj(
        context.get_admin_context(),
        expected_attrs=[
            v for (k, v) in expected_attrs_key.items() if k in kwargs],
        **kwargs)


def _fake_cg_wrapper(*args, **kwargs):
    return fake_consistencygroup.fake_consistencyobject_obj(
        'fake_context', **kwargs)


def _fake_snapshot_wrapper(*args, **kwargs):
    return fake_snapshot.fake_snapshot_obj('fake_context',
                                           expected_attrs=(
                                               ['volume'] if 'volume' in kwargs
                                               else None),
                                           **kwargs)


def _fake_cg_snapshot_wrapper(*args, **kwargs):
    return fake_cgsnapshot.fake_cgsnapshot_obj(None, **kwargs)


def _fake_group_wrapper(*args, **kwargs):
    return fake_group.fake_group_obj(None, **kwargs)


class EnumBuilder(object):
    def __init__(self, enum_dict):
        enum_dict = enum_dict[SYMBOL_ENUM]
        for k, v in enum_dict.items():
            self.klazz = k
            self.value = v

    def __call__(self, *args, **kwargs):
        return getattr(storops, self.klazz).parse(self.value)


class CinderResourceMock(DriverResourceMock):
    # fake_func in the mapping should be like func(*args, **kwargs)
    fake_func_mapping = {'volume': _fake_volume_wrapper,
                         'cg': _fake_cg_wrapper,
                         'snapshot': _fake_snapshot_wrapper,
                         'cg_snapshot': _fake_cg_snapshot_wrapper,
                         'group': _fake_group_wrapper}

    def __init__(self, yaml_file):
        super(CinderResourceMock, self).__init__(yaml_file)

    @staticmethod
    def _build_provider_location(props):
        return vnx_utils.build_provider_location(
            props.get('system'), props.get('type'),
            six.text_type(props.get('id')),
            six.text_type(props.get('base_lun_name')),
            props.get('version'))


class ContextMock(object):
    """Mocks the return value of a context function."""

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_valu, exc_tb):
        pass


class MockBase(object):
    """Base object of all the Mocks.

    This mock convert the dict to object when the '_type' is
    included in the dict
    """

    def _is_mock_object(self, yaml_info):
        return (isinstance(yaml_info, dict) and
                (SYMBOL_PROPERTIES in yaml_info or
                 SYMBOL_METHODS in yaml_info))

    def _is_object_with_type(self, yaml_dict):
        return isinstance(yaml_dict, dict) and SYMBOL_TYPE in yaml_dict

    def _is_object_with_enum(self, yaml_dict):
        return isinstance(yaml_dict, dict) and SYMBOL_ENUM in yaml_dict

    def _build_mock_object(self, yaml_dict):
        if self._is_object_with_type(yaml_dict):
            return FakePort(yaml_dict)
        elif self._is_object_with_enum(yaml_dict):
            return EnumBuilder(yaml_dict)()
        elif self._is_mock_object(yaml_dict):
            return StorageObjectMock(yaml_dict)
        elif isinstance(yaml_dict, dict):
            return {k: self._build_mock_object(v)
                    for k, v in yaml_dict.items()}
        elif isinstance(yaml_dict, list):
            return [self._build_mock_object(each) for each in yaml_dict]
        else:
            return yaml_dict


class StorageObjectMock(object):
    PROPS = 'props'

    def __init__(self, yaml_dict):
        self.__dict__[StorageObjectMock.PROPS] = {}
        props = yaml_dict.get(SYMBOL_PROPERTIES, None)
        if props:
            for k, v in props.items():
                setattr(self, k, StoragePropertyMock(k, v)())

        methods = yaml_dict.get(SYMBOL_METHODS, None)
        if methods:
            for k, v in methods.items():
                setattr(self, k, StorageMethodMock(k, v))

    def __setattr__(self, key, value):
        self.__dict__[StorageObjectMock.PROPS][key] = value

    def __getattr__(self, item):
        try:
            super(StorageObjectMock, self).__getattr__(item)
        except AttributeError:
            return self.__dict__[StorageObjectMock.PROPS][item]
        except KeyError:
            raise KeyError('%(item)s not exist in mock object.'
                           ) % {'item': item}


class FakePort(StorageObjectMock):

    def __eq__(self, other):
        o_sp = other.sp
        o_port_id = other.port_id
        o_vport_id = other.vport_id

        ret = True
        ret &= self.sp == o_sp
        ret &= self.port_id == o_port_id
        ret &= self.vport_id == o_vport_id

        return ret

    def __hash__(self):
        return hash((self.sp, self.port_id, self.vport_id))


class StoragePropertyMock(mock.PropertyMock, MockBase):
    def __init__(self, name, property_body):
        return_value = property_body
        side_effect = None

        # only support return_value and side_effect for property
        if (isinstance(property_body, dict) and
                SYMBOL_SIDE_EFFECT in property_body):
            side_effect = self._build_mock_object(
                property_body[SYMBOL_SIDE_EFFECT])
            return_value = None

        if side_effect is not None:
            super(StoragePropertyMock, self).__init__(
                name=name,
                side_effect=side_effect)
        else:
            return_value = self._build_mock_object(return_value)

            super(StoragePropertyMock, self).__init__(
                name=name,
                return_value=return_value)


class StorageMethodMock(mock.Mock, MockBase):
    def __init__(self, name, method_body):
        return_value = method_body
        exception = None
        side_effect = None

        # support return_value, side_effect and exception for method
        if isinstance(method_body, dict):
            if (SYMBOL_SIDE_EFFECT in method_body or
                    SYMBOL_RAISE in method_body):
                exception = method_body.get(SYMBOL_RAISE, None)
                side_effect = method_body.get(SYMBOL_SIDE_EFFECT, None)
                return_value = None

        if exception is not None:
            ex = None
            if isinstance(exception, dict) and exception:
                ex_name = list(exception.keys())[0]
                ex_tmp = [getattr(ex_module, ex_name, None)
                          for ex_module in [lib_ex, common]]
                try:
                    ex = [each for each in ex_tmp if each is not None][0]
                    super(StorageMethodMock, self).__init__(
                        name=name,
                        side_effect=ex(exception[ex_name]))
                except IndexError:
                    raise KeyError('Exception %(ex_name)s not found.'
                                   % {'ex_name': ex_name})
            else:
                raise KeyError('Invalid Exception body, should be a dict.')
        elif side_effect is not None:
            super(StorageMethodMock, self).__init__(
                name=name,
                side_effect=self._build_mock_object(side_effect))
        elif return_value is not None:
            super(StorageMethodMock, self).__init__(
                name=name,
                return_value=(ContextMock() if return_value == SYMBOL_CONTEXT
                              else self._build_mock_object(return_value)))
        else:
            super(StorageMethodMock, self).__init__(
                name=name, return_value=None)


class StorageResourceMock(dict, MockBase):
    def __init__(self, yaml_file):
        yaml_dict = utils.load_yaml(yaml_file)
        if not isinstance(yaml_dict, dict):
            return
        for section, sec_body in yaml_dict.items():
            if isinstance(sec_body, dict):
                self[section] = {obj_name: self._build_mock_object(obj_body)
                                 for obj_name, obj_body
                                 in sec_body.items()}
            else:
                self[section] = {}


cinder_res = CinderResourceMock('mocked_cinder.yaml')
DRIVER_RES_MAPPING = {
    'TestResMock': cinder_res,
    'TestCommonAdapter': cinder_res,
    'TestReplicationAdapter': cinder_res,
    'TestISCSIAdapter': cinder_res,
    'TestFCAdapter': cinder_res,
    'TestUtils': cinder_res,
    'TestClient': cinder_res
}


def mock_driver_input(func):
    @six.wraps(func)
    def decorated(cls, *args, **kwargs):
        return func(cls,
                    DRIVER_RES_MAPPING[cls.__class__.__name__][func.__name__],
                    *args, **kwargs)
    return decorated


vnx_res = StorageResourceMock('mocked_vnx.yaml')
STORAGE_RES_MAPPING = {
    'TestResMock': StorageResourceMock('test_res_mock.yaml'),
    'TestCondition': vnx_res,
    'TestClient': vnx_res,
    'TestCommonAdapter': vnx_res,
    'TestReplicationAdapter': vnx_res,
    'TestISCSIAdapter': vnx_res,
    'TestFCAdapter': vnx_res,
    'TestTaskflow': vnx_res,
    'TestExtraSpecs': vnx_res,
}
DEFAULT_STORAGE_RES = 'vnx'


def _build_client():
    return client.Client(ip='192.168.1.2',
                         username='sysadmin',
                         password='sysadmin',
                         scope='global',
                         naviseccli=None,
                         sec_file=None,
                         queue_path='vnx-cinder')


def patch_client(func):
    @six.wraps(func)
    def decorated(cls, *args, **kwargs):
        storage_res = (
            STORAGE_RES_MAPPING[cls.__class__.__name__][func.__name__])
        with utils.patch_vnxsystem as patched_vnx:
            if DEFAULT_STORAGE_RES in storage_res:
                patched_vnx.return_value = storage_res[DEFAULT_STORAGE_RES]
            client = _build_client()
        return func(cls, client, storage_res, *args, **kwargs)
    return decorated


PROTOCOL_COMMON = 'Common'
PROTOCOL_MAPPING = {
    PROTOCOL_COMMON: adapter.CommonAdapter,
    common.PROTOCOL_ISCSI: adapter.ISCSIAdapter,
    common.PROTOCOL_FC: adapter.FCAdapter
}


def patch_adapter_init(protocol):
    def inner_patch_adapter(func):
        @six.wraps(func)
        def decorated(cls, *args, **kwargs):
            storage_res = (
                STORAGE_RES_MAPPING[cls.__class__.__name__][func.__name__])
            with utils.patch_vnxsystem as patched_vnx:
                if DEFAULT_STORAGE_RES in storage_res:
                    patched_vnx.return_value = storage_res[DEFAULT_STORAGE_RES]
                adapter = PROTOCOL_MAPPING[protocol](cls.configuration)
            return func(cls, adapter, storage_res, *args, **kwargs)
        return decorated
    return inner_patch_adapter


def _patch_adapter_prop(adapter, client):
    try:
        adapter.serial_number = client.get_serial()
    except KeyError:
        adapter.serial_number = 'faked_serial_number'
    adapter.VERSION = driver.VNXDriver.VERSION


def patch_adapter(protocol):
    def inner_patch_adapter(func):
        @six.wraps(func)
        def decorated(cls, *args, **kwargs):
            storage_res = (
                STORAGE_RES_MAPPING[cls.__class__.__name__][func.__name__])
            with utils.patch_vnxsystem:
                client = _build_client()
                adapter = PROTOCOL_MAPPING[protocol](cls.configuration, None)
            if DEFAULT_STORAGE_RES in storage_res:
                client.vnx = storage_res[DEFAULT_STORAGE_RES]
            adapter.client = client
            _patch_adapter_prop(adapter, client)
            return func(cls, adapter, storage_res, *args, **kwargs)
        return decorated
    return inner_patch_adapter


patch_common_adapter = patch_adapter(PROTOCOL_COMMON)
patch_iscsi_adapter = patch_adapter(common.PROTOCOL_ISCSI)
patch_fc_adapter = patch_adapter(common.PROTOCOL_FC)


def mock_storage_resources(func):
    @six.wraps(func)
    def decorated(cls, *args, **kwargs):
        storage_res = (
            STORAGE_RES_MAPPING[cls.__class__.__name__][func.__name__])
        return func(cls, storage_res, *args, **kwargs)
    return decorated
