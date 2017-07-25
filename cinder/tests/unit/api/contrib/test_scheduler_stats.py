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

import ddt
import mock
import webob

from cinder.api.contrib import scheduler_stats
from cinder.api.openstack import api_version_request as api_version
from cinder import context
from cinder import exception
from cinder import test
from cinder.tests.unit.api import fakes
from cinder.tests.unit import fake_constants as fake


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


@ddt.ddt
class SchedulerStatsAPITest(test.TestCase):
    def setUp(self):
        super(SchedulerStatsAPITest, self).setUp()
        self.flags(host='fake')
        self.controller = scheduler_stats.SchedulerStatsController()
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID, True)

    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.get_pools',
                schedule_rpcapi_get_pools)
    def test_get_pools_summary(self):
        req = fakes.HTTPRequest.blank('/v2/%s/scheduler_stats' %
                                      fake.PROJECT_ID)
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

        self.assertDictEqual(expected, res)

    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.get_pools')
    def test_get_pools_summary_filter_name(self, mock_rpcapi):
        req = fakes.HTTPRequest.blank('/v3/%s/scheduler_stats?name=pool1' %
                                      fake.PROJECT_ID)
        mock_rpcapi.return_value = [dict(name='pool1',
                                         capabilities=dict(foo='bar'))]
        req.api_version_request = api_version.APIVersionRequest('3.28')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.get_pools(req)

        expected = {
            'pools': [
                {
                    'name': 'pool1',
                }
            ]
        }

        self.assertDictEqual(expected, res)
        filters = {'name': 'pool1'}
        mock_rpcapi.assert_called_with(mock.ANY, filters=filters)

    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.get_pools')
    def test_get_pools_summary_filter_capabilities(self, mock_rpcapi):
        req = fakes.HTTPRequest.blank('/v3/%s/scheduler_stats?detail=True'
                                      '&foo=bar' % fake.PROJECT_ID)
        mock_rpcapi.return_value = [dict(name='pool1',
                                         capabilities=dict(foo='bar'))]
        req.api_version_request = api_version.APIVersionRequest('3.28')
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.get_pools(req)

        expected = {
            'pools': [
                {
                    'name': 'pool1',
                    'capabilities': {
                        'foo': 'bar'
                    }
                }
            ]
        }

        self.assertDictEqual(expected, res)
        filters = {'foo': 'bar'}
        mock_rpcapi.assert_called_with(mock.ANY, filters=filters)

    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.get_pools',
                schedule_rpcapi_get_pools)
    def test_get_pools_detail(self):
        req = fakes.HTTPRequest.blank('/v2/%s/scheduler_stats?detail=True' %
                                      fake.PROJECT_ID)
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

        self.assertDictEqual(expected, res)

    def test_get_pools_detail_invalid_bool(self):
        req = fakes.HTTPRequest.blank(
            '/v2/%s/scheduler_stats?detail=InvalidBool' %
            fake.PROJECT_ID)
        req.environ['cinder.context'] = self.ctxt
        self.assertRaises(exception.InvalidParameterValue,
                          self.controller.get_pools,
                          req)

    @ddt.data(('3.34', False),
              ('3.35', True))
    @ddt.unpack
    @mock.patch('cinder.scheduler.rpcapi.SchedulerAPI.get_pools')
    @mock.patch('cinder.api.common.reject_invalid_filters')
    def test_get_pools_by_volume_type(self,
                                      version,
                                      support_volume_type,
                                      mock_reject_invalid_filters,
                                      mock_get_pools
                                      ):
        req = fakes.HTTPRequest.blank('/v3/%s/scheduler-stats/get_pools?'
                                      'volume_type=lvm' % fake.PROJECT_ID)
        mock_get_pools.return_value = [{'name': 'pool1',
                                        'capabilities': {'foo': 'bar'}}]
        req.api_version_request = api_version.APIVersionRequest(version)
        req.environ['cinder.context'] = self.ctxt
        res = self.controller.get_pools(req)

        expected = {
            'pools': [{'name': 'pool1'}]
        }

        filters = dict()
        if support_volume_type:
            filters = {'volume_type': 'lvm'}
        filters = webob.multidict.MultiDict(filters)
        mock_reject_invalid_filters.assert_called_once_with(self.ctxt, filters,
                                                            'pool', True)
        self.assertDictEqual(expected, res)
        mock_get_pools.assert_called_with(mock.ANY, filters=filters)
