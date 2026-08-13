# (c) Copyright 2025 Hewlett Packard Enterprise Development LP
#    All Rights Reserved.
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
"""Fake HPE storage flowkit for testing Alletra MP without installing
    the flowkit."""

import sys
from types import ModuleType
from unittest import mock

from oslo_log import log as logging

# Import fake modules first to ensure they're loaded
from cinder.tests.unit.volume.drivers.hpe \
    import fake_hpe_flowkit_exceptions as flowkit_exceptions
from cinder.tests.unit.volume.drivers.hpe \
    import fake_hpeflowkit  # noqa

# Get the hpeflowkit module that was set up in fake_hpeflowkit
hpeflowkit = sys.modules['hpeflowkit']

LOG = logging.getLogger(__name__)


def _make_module(name, package=False):
    module = ModuleType(name)
    if package:
        module.__path__ = []
    return module


def _register(module):
    sys.modules[module.__name__] = module
    return module


def _workflow_class(name):
    return type(name, (), {
        '__init__': lambda self, *args, **kwargs: None,
        'get_ws_api_version': lambda self, *args, **kwargs: {
            'build': 100500000,
        },
        'get_storage_system_info': lambda self, *args, **kwargs: {
            'id': 1,
        },
    })


def _get_alletramp_volume_name(volume):
    volume_id = getattr(volume, 'id', None)
    if volume_id is None and isinstance(volume, dict):
        volume_id = volume.get('id')
    return f'volume-{volume_id}'


def _initialize_nvme_connection(storage_client, vol_name, connector, nvme_ips,
                                vlun_workflow_cls, volume_workflow_cls,
                                logger=None):
    vlun_workflow = vlun_workflow_cls(storage_client.session_mgr)
    volume_workflow = volume_workflow_cls(storage_client.session_mgr)
    host_nqn = connector['nqn']
    host = vlun_workflow.getHostByNqn(host_nqn)

    if logger is not None:
        logger.debug("host: %(host)s", {'host': host})

    if not host:
        raise LookupError(host_nqn)

    portals, target_nqns = vlun_workflow.create_vlun_nvme(
        vol_name, host, nvme_ips)
    vlun = vlun_workflow.getVLUN(vol_name)
    storage_volume = volume_workflow.get_volume(vol_name)

    return {
        'portals': portals,
        'target_nqn': target_nqns[0],
        'host_nqn': host_nqn,
        'target_lun': vlun.get('lun', 0),
        'vol_uuid': storage_volume['nguid'],
        'access_mode': 'rw',
    }


def _terminate_nvme_connection(storage_client, vol_name, connector,
                               should_skip_terminate, vlun_workflow_cls,
                               logger=None):
    vlun_workflow = vlun_workflow_cls(storage_client.session_mgr)

    if connector is None:
        vlun_workflow.remove_vlun_nvme(vol_name, None, None)
        return

    if should_skip_terminate(vol_name, connector['host']):
        return

    host_nqn = connector['nqn']
    host = vlun_workflow.getHostByNqn(host_nqn)

    if logger is not None:
        logger.debug("host: %(host)s", {'host': host})

    hostname = host['name']
    vlun_workflow.remove_vlun_nvme(vol_name, hostname, host_nqn)


flowkit = _register(_make_module('hpe_storage_flowkit_py', package=True))
flowkit.version = "1.0"

flowkit_v1 = _register(_make_module('hpe_storage_flowkit_py.v1', package=True))
flowkit_v3 = _register(_make_module('hpe_storage_flowkit_py.v3', package=True))
flowkit_v1_src = _register(
    _make_module('hpe_storage_flowkit_py.v1.src', package=True))
flowkit_v3_src = _register(
    _make_module('hpe_storage_flowkit_py.v3.src', package=True))
flowkit_v1_core = _register(
    _make_module('hpe_storage_flowkit_py.v1.src.core', package=True))
flowkit_v3_core = _register(
    _make_module('hpe_storage_flowkit_py.v3.src.core', package=True))
flowkit_v1_workflows = _register(
    _make_module('hpe_storage_flowkit_py.v1.src.workflows', package=True))
flowkit_v3_workflows = _register(
    _make_module('hpe_storage_flowkit_py.v3.src.workflows', package=True))
flowkit_v1_utils = _register(
    _make_module('hpe_storage_flowkit_py.v1.src.utils', package=True))
flowkit_v1_top_utils = _register(
    _make_module('hpe_storage_flowkit_py.v1.utils', package=True))
flowkit_services = _register(
    _make_module('hpe_storage_flowkit_py.services', package=True))
flowkit_services_src = _register(
    _make_module('hpe_storage_flowkit_py.services.src', package=True))

flowkit.v1 = flowkit_v1
flowkit.v3 = flowkit_v3
flowkit.services = flowkit_services
flowkit_v1.src = flowkit_v1_src
flowkit_v3.src = flowkit_v3_src
flowkit_v1.utils = flowkit_v1_top_utils
flowkit_v1_src.core = flowkit_v1_core
flowkit_v3_src.core = flowkit_v3_core
flowkit_v1_src.workflows = flowkit_v1_workflows
flowkit_v3_src.workflows = flowkit_v3_workflows
flowkit_v1_src.utils = flowkit_v1_utils
flowkit_services.src = flowkit_services_src

flowkit_src_core_exceptions = _register(
    _make_module('hpe_storage_flowkit_py.v1.src.core.exceptions'))
flowkit_src_core_exceptions.HPEStorageException = (
    flowkit_exceptions.HPEStorageException)
flowkit_src_core_exceptions.HTTPBadRequest = (
    flowkit_exceptions.HTTPBadRequest)
flowkit_src_core_exceptions.HTTPForbidden = (
    flowkit_exceptions.HTTPForbidden)
flowkit_src_core_exceptions.HTTPNotFound = (
    flowkit_exceptions.HTTPNotFound)
flowkit_src_core_exceptions.HTTPConflict = (
    flowkit_exceptions.HTTPConflict)
flowkit_v1_core.exceptions = flowkit_src_core_exceptions

flowkit_src_core_session = _register(
    _make_module('hpe_storage_flowkit_py.v1.src.core.session'))
flowkit_src_core_session.SessionManager = mock.Mock()
flowkit_v1_core.session = flowkit_src_core_session

flowkit_v3_src_core_session = _register(
    _make_module('hpe_storage_flowkit_py.v3.src.core.session'))
flowkit_v3_src_core_session.SessionManager = mock.Mock()
flowkit_v3_core.session = flowkit_v3_src_core_session

flowkit_src_utils_constants = _register(
    _make_module('hpe_storage_flowkit_py.v1.src.utils.constants'))
flowkit_v1_utils.constants = flowkit_src_utils_constants
sys.modules['hpe_storage_flowkit_py.v1.utils.constants'] = (
    flowkit_src_utils_constants)
flowkit_v1_top_utils.constants = flowkit_src_utils_constants

flowkit_src_workflows_volume = _register(
    _make_module('hpe_storage_flowkit_py.v1.src.workflows.volume'))
VolumeWorkflow = _workflow_class('VolumeWorkflow')
VolumeWorkflow.grow_volume = mock.Mock()
flowkit_src_workflows_volume.VolumeWorkflow = VolumeWorkflow

flowkit_src_workflows_host = _register(
    _make_module('hpe_storage_flowkit_py.v1.src.workflows.host'))
flowkit_src_workflows_host.HostWorkflow = _workflow_class('HostWorkflow')

flowkit_src_workflows_vlun = _register(
    _make_module('hpe_storage_flowkit_py.v1.src.workflows.vlun'))
flowkit_src_workflows_vlun.VLUNWorkflow = _workflow_class('VLUNWorkflow')

for module_name, attr_name in [
        ('snapshot', 'SnapshotWorkflow'),
        ('system', 'SystemWorkflow'),
        ('cpg', 'CPGWorkflow'),
        ('task_manager', 'TaskManager'),
        ('remote_copy', 'RemoteCopyGroupWorkflow'),
        ('volumeset', 'VolumeSetWorkflow'),
        ('qos', 'QOSWorkflow')]:
    workflow_module = _register(
        _make_module(f'hpe_storage_flowkit_py.v1.src.workflows.{module_name}'))
    workflow_cls = _workflow_class(attr_name)

    if attr_name == 'SnapshotWorkflow':
        workflow_cls.delete_snapshot = mock.Mock()
    elif attr_name == 'RemoteCopyGroupWorkflow':
        workflow_cls.get_remote_copy_group = mock.Mock()
    elif attr_name == 'QOSWorkflow':
        workflow_cls.create_qos = mock.Mock()
        workflow_cls.modify_qos = mock.Mock()

    setattr(workflow_module, attr_name, workflow_cls)
    setattr(flowkit_v1_workflows, module_name, workflow_module)

flowkit_v1_workflows.volume = flowkit_src_workflows_volume
flowkit_v1_workflows.host = flowkit_src_workflows_host
flowkit_v1_workflows.vlun = flowkit_src_workflows_vlun

for module_name, attr_name in [
        ('task', 'TaskManager'),
        ('remote_copy', 'RemoteCopyGroupWorkflow'),
        ('host', 'HostWorkflow')]:
    workflow_module = _register(
        _make_module(f'hpe_storage_flowkit_py.v3.src.workflows.{module_name}'))
    setattr(workflow_module, attr_name, _workflow_class(attr_name))
    setattr(flowkit_v3_workflows, module_name, workflow_module)

iscsi_connection_utils = _register(
    _make_module('hpe_storage_flowkit_py.services.src.iscsi_connection_utils'))
iscsi_connection_utils.create_iscsi_export_credentials = mock.Mock(
    return_value=(None, None))
iscsi_connection_utils.ensure_iscsi_export_credentials = mock.Mock(
    return_value=(None, None))
sys.modules['hpe_storage_flowkit_py.v1.utils.iscsi_connection_utils'] = (
    iscsi_connection_utils)
sys.modules['hpe_storage_flowkit_py.v1.src.utils.iscsi_connection_utils'] = (
    iscsi_connection_utils)
flowkit_v1_top_utils.iscsi_connection_utils = iscsi_connection_utils
flowkit_v1_utils.iscsi_connection_utils = iscsi_connection_utils

nvme_connection_utils = _register(
    _make_module('hpe_storage_flowkit_py.services.src.nvme_connection_utils'))
nvme_connection_utils.get_configured_nvme_ip_map = mock.Mock(return_value={})
nvme_connection_utils.initialize_nvme_connection = mock.Mock(
    side_effect=_initialize_nvme_connection)
nvme_connection_utils.terminate_nvme_connection = mock.Mock(
    side_effect=_terminate_nvme_connection)
sys.modules['hpe_storage_flowkit_py.v1.utils.nvme_connection_utils'] = (
    nvme_connection_utils)
sys.modules['hpe_storage_flowkit_py.v1.src.utils.nvme_connection_utils'] = (
    nvme_connection_utils)
flowkit_v1_top_utils.nvme_connection_utils = nvme_connection_utils
flowkit_v1_utils.nvme_connection_utils = nvme_connection_utils

flowkit_services_src.cinder_service = hpeflowkit
flowkit_services_src.iscsi_connection_utils = iscsi_connection_utils
flowkit_services_src.nvme_connection_utils = nvme_connection_utils
flowkit.flowkit_exceptions = flowkit_src_core_exceptions
