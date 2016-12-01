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

import sys

import mock

from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_exception
from cinder.tests.unit.volume.drivers.dell_emc.vnx import fake_storops

fake_vnx = mock.Mock()
fake_storops.exception = fake_exception
fake_storops.vnx = fake_vnx
sys.modules['storops'] = fake_storops
