# Copyright (c) 2015 Alex Meade.  All rights reserved.
# Copyright (c) 2015 Michael Price.  All rights reserved.
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

import ddt
import mock

from cinder import test

from cinder.tests.unit.volume.drivers.netapp.eseries import test_driver
from cinder.volume.drivers.netapp.eseries import iscsi_driver as iscsi
import cinder.volume.drivers.netapp.utils as na_utils


@ddt.ddt
class NetAppESeriesIscsiDriverTestCase(test_driver.NetAppESeriesDriverTestCase,
                                       test.TestCase):

    @mock.patch.object(na_utils, 'validate_instantiation')
    def test_instantiation(self, mock_validate_instantiation):
        iscsi.NetAppEseriesISCSIDriver(configuration=mock.Mock())
