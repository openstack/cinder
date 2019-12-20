#  Copyright (c) 2016 IBM Corporation
#  All Rights Reserved.
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
""" Fake pyxcli-client for testing the driver without installing pyxcli"""
import sys
from unittest import mock

from cinder.tests.unit.volume.drivers.ibm import fake_pyxcli_exceptions


pyxcli_client = mock.Mock()
pyxcli_client.errors = fake_pyxcli_exceptions
pyxcli_client.events = mock.Mock()
pyxcli_client.mirroring = mock.Mock()
pyxcli_client.transports = fake_pyxcli_exceptions
pyxcli_client.mirroring.cg_recovery_manager = mock.Mock()
pyxcli_client.version = '1.1.6'
pyxcli_client.mirroring.mirrored_entities = mock.Mock()

sys.modules['pyxcli'] = pyxcli_client
sys.modules['pyxcli.events'] = pyxcli_client.events
sys.modules['pyxcli.mirroring'] = pyxcli_client.mirroring
