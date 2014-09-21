# Copyright 2013 eBay Inc.
# Copyright 2013 OpenStack Foundation
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

import mock

from cinder.api.contrib import scheduler_stats
from cinder import context
from cinder import test
from cinder.tests.api import fakes


def schedule_rpcapi_get_pools(self, context, filters=None):
    all_pools = []
    pool1 = dict(name='pool1',
                 capabilities=dict(
                     total_capacity=1024, free_capacity=100,
                     volume_backend_name='pool1', reserved_percentage=0,
                     driver_version='1.0.0', storage_protocol='iSCSI',
                     QoS_support='False', updated=None))
    all_pools.append(pool1)
    pool2 = dict(name='pool2',
                 capabilities=dict(
                     total_capacity=512, free_capacity=200,
                     volume_backend_name='pool2', reserved_percentage=0,
                     driver_version='1.0.1', storage_protocol='iSER',
                     QoS_support='True', updated=None))
    all_pools.append(pool2)

    return all_pools


@mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.get_pools',
            schedule_rpcapi_get_pools)
class SchedulerStatsAPITest(test.TestCase):
    def setUp(self):
        super(SchedulerStatsAPITest, self).setUp()
        self.flags(host='fake')
        self.controller = scheduler_stats.SchedulerStatsController()
        self.ctxt = context.RequestContext('admin', 'fake', True)

    def test_get_pools_summery(self):
        req = fakes.HTTPRequest.blank('/v2/fake/scheduler_stats')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.get_pools(req)

        self.assertEqual(2, len(res['pools']))

        expected = {
            'pools': [
                {
                    'name': 'pool1',
                },
                {
                    'name': 'pool2',
                }
            ]
        }

        self.assertDictMatch(res, expected)

    def test_get_pools_detail(self):
        req = fakes.HTTPRequest.blank('/v2/fake/scheduler_stats?detail=True')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.get_pools(req)

        self.assertEqual(2, len(res['pools']))

        expected = {
            'pools': [
                {
                    'name': 'pool1',
                    'capabilities': {
                        'updated': None,
                        'total_capacity': 1024,
                        'free_capacity': 100,
                        'volume_backend_name': 'pool1',
                        'reserved_percentage': 0,
                        'driver_version': '1.0.0',
                        'storage_protocol': 'iSCSI',
                        'QoS_support': 'False', }
                },
                {
                    'name': 'pool2',
                    'capabilities': {
                        'updated': None,
                        'total_capacity': 512,
                        'free_capacity': 200,
                        'volume_backend_name': 'pool2',
                        'reserved_percentage': 0,
                        'driver_version': '1.0.1',
                        'storage_protocol': 'iSER',
                        'QoS_support': 'True', }
                }
            ]
        }

        self.assertDictMatch(res, expected)
