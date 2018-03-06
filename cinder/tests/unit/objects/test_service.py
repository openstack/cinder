#    Copyright 2015 Intel Corp.
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

import datetime
import ddt
import mock
from oslo_utils import timeutils
import pytz
import six

from cinder import exception
from cinder import objects
from cinder.tests.unit import fake_cluster
from cinder.tests.unit import fake_service
from cinder.tests.unit import objects as test_objects


@ddt.ddt
class TestService(test_objects.BaseObjectsTestCase):

    @mock.patch('cinder.db.sqlalchemy.api.service_get')
    def test_get_by_id(self, service_get):
        db_service = fake_service.fake_db_service()
        service_get.return_value = db_service
        service = objects.Service.get_by_id(self.context, 1)
        self._compare(self, db_service, service)
        service_get.assert_called_once_with(self.context, 1)

    @ddt.data(True, False)
    @mock.patch('cinder.db.service_get')
    def test_get_by_host_and_topic(self, show_disabled, service_get):
        db_service = fake_service.fake_db_service()
        service_get.return_value = db_service
        service = objects.Service.get_by_host_and_topic(
            self.context, 'fake-host', 'fake-topic', disabled=show_disabled)
        self._compare(self, db_service, service)
        service_get.assert_called_once_with(
            self.context, disabled=show_disabled, host='fake-host',
            topic='fake-topic')

    @mock.patch('cinder.db.service_get')
    def test_get_by_args(self, service_get):
        db_service = fake_service.fake_db_service()
        service_get.return_value = db_service
        service = objects.Service.get_by_args(
            self.context, 'fake-host', 'fake-key')
        self._compare(self, db_service, service)
        service_get.assert_called_once_with(
            self.context, host='fake-host', binary='fake-key')

    @mock.patch('cinder.db.service_create')
    def test_create(self, service_create):
        db_service = fake_service.fake_db_service()
        service_create.return_value = db_service
        service = objects.Service(context=self.context)
        service.create()
        self.assertEqual(db_service['id'], service.id)
        service_create.assert_called_once_with(self.context,
                                               {'uuid': mock.ANY})

    @mock.patch('cinder.db.service_update')
    def test_save(self, service_update):
        db_service = fake_service.fake_db_service()
        service = objects.Service._from_db_object(
            self.context, objects.Service(), db_service)
        service.topic = 'foobar'
        service.save()
        service_update.assert_called_once_with(self.context, service.id,
                                               {'topic': 'foobar'})

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=timeutils.utcnow())
    @mock.patch('cinder.db.sqlalchemy.api.service_destroy')
    def test_destroy(self, service_destroy, utcnow_mock):
        service_destroy.return_value = {
            'deleted': True,
            'deleted_at': utcnow_mock.return_value}
        db_service = fake_service.fake_db_service()
        service = objects.Service._from_db_object(
            self.context, objects.Service(), db_service)
        with mock.patch.object(service._context, 'elevated') as elevated_ctx:
            service.destroy()
            service_destroy.assert_called_once_with(elevated_ctx(), 123)
        self.assertTrue(service.deleted)
        self.assertEqual(utcnow_mock.return_value.replace(tzinfo=pytz.UTC),
                         service.deleted_at)

    @mock.patch('cinder.db.sqlalchemy.api.service_get')
    def test_refresh(self, service_get):
        db_service1 = fake_service.fake_db_service()
        db_service2 = db_service1.copy()
        db_service2['availability_zone'] = 'foobar'

        # On the second service_get, return the service with an updated
        # availability_zone
        service_get.side_effect = [db_service1, db_service2]
        service = objects.Service.get_by_id(self.context, 123)
        self._compare(self, db_service1, service)

        # availability_zone was updated, so a service refresh should have a
        # new value for that field
        service.refresh()
        self._compare(self, db_service2, service)
        if six.PY3:
            call_bool = mock.call.__bool__()
        else:
            call_bool = mock.call.__nonzero__()
        service_get.assert_has_calls([mock.call(self.context, 123),
                                      call_bool,
                                      mock.call(self.context, 123)])

    @mock.patch('cinder.db.service_get_all')
    def test_get_minimum_version(self, service_get_all):
        services_update = [
            {'rpc_current_version': '1.0', 'object_current_version': '1.3'},
            {'rpc_current_version': '1.1', 'object_current_version': '1.2'},
            {'rpc_current_version': '2.0', 'object_current_version': '2.5'},
        ]
        expected = ('1.0', '1.2')
        services = [fake_service.fake_db_service(**s) for s in services_update]
        service_get_all.return_value = services

        min_rpc = objects.Service.get_minimum_rpc_version(self.context, 'foo')
        self.assertEqual(expected[0], min_rpc)
        min_obj = objects.Service.get_minimum_obj_version(self.context, 'foo')
        self.assertEqual(expected[1], min_obj)
        service_get_all.assert_has_calls(
            [mock.call(self.context, binary='foo', disabled=None)] * 2)

    @mock.patch('cinder.db.service_get_all')
    def test_get_minimum_version_liberty(self, service_get_all):
        services_update = [
            {'rpc_current_version': '1.0', 'object_current_version': '1.3'},
            {'rpc_current_version': '1.1', 'object_current_version': None},
            {'rpc_current_version': None, 'object_current_version': '2.5'},
        ]
        services = [fake_service.fake_db_service(**s) for s in services_update]
        service_get_all.return_value = services

        self.assertRaises(exception.ServiceTooOld,
                          objects.Service.get_minimum_rpc_version,
                          self.context, 'foo')
        self.assertRaises(exception.ServiceTooOld,
                          objects.Service.get_minimum_obj_version,
                          self.context, 'foo')

    @mock.patch('cinder.db.service_get_all')
    def test_get_minimum_version_no_binary(self, service_get_all):
        services_update = [
            {'rpc_current_version': '1.0', 'object_current_version': '1.3'},
            {'rpc_current_version': '1.1', 'object_current_version': '1.2'},
            {'rpc_current_version': '2.0', 'object_current_version': '2.5'},
        ]
        services = [fake_service.fake_db_service(**s) for s in services_update]
        service_get_all.return_value = services

        min_obj = objects.Service.get_minimum_obj_version(self.context)
        self.assertEqual('1.2', min_obj)
        service_get_all.assert_called_once_with(self.context, binary=None,
                                                disabled=None)

    @mock.patch('cinder.db.sqlalchemy.api.cluster_get')
    def test_lazy_loading_cluster_field(self, cluster_get):
        cluster_orm = fake_cluster.fake_cluster_orm(name='mycluster')
        cluster_get.return_value = cluster_orm
        cluster = objects.Cluster._from_db_object(self.context,
                                                  objects.Cluster(),
                                                  cluster_orm)

        service = fake_service.fake_service_obj(self.context,
                                                cluster_name='mycluster')
        self.assertEqual(cluster, service.cluster)
        cluster_get.assert_called_once_with(self.context, None,
                                            name='mycluster')

    def test_service_is_up(self):
        # NOTE(mdovgal): don't use @ddt.data with the real timestamp value
        # for this test.
        # When using ddt decorators ddt.data seems to have been calculated
        # not at the time of test's execution but at the tests's beginning.
        # And this one depends on utcnow func. So it won't be utcnow at the
        # execution moment and the result will be unexpected.
        down_time = 5
        self.flags(service_down_time=down_time)

        # test if service is up
        service = fake_service.fake_service_obj(self.context)
        self.assertTrue(service.is_up)

        service.updated_at = timeutils.utcnow()
        self.assertTrue(service.is_up)

        # test is service is down now
        past_time = timeutils.utcnow() - datetime.timedelta(seconds=64)
        service.updated_at = past_time
        self.assertFalse(service.is_up)


class TestServiceList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.db.service_get_all')
    def test_get_all(self, service_get_all):
        db_service = fake_service.fake_db_service()
        service_get_all.return_value = [db_service]

        filters = {'host': 'host', 'binary': 'foo', 'disabled': False}
        services = objects.ServiceList.get_all(self.context, filters)
        service_get_all.assert_called_once_with(self.context, **filters)
        self.assertEqual(1, len(services))
        TestService._compare(self, db_service, services[0])

    @mock.patch('cinder.db.service_get_all')
    def test_get_all_by_topic(self, service_get_all):
        db_service = fake_service.fake_db_service()
        service_get_all.return_value = [db_service]

        services = objects.ServiceList.get_all_by_topic(
            self.context, 'foo', 'bar')
        service_get_all.assert_called_once_with(
            self.context, topic='foo', disabled='bar')
        self.assertEqual(1, len(services))
        TestService._compare(self, db_service, services[0])

    @mock.patch('cinder.db.service_get_all')
    def test_get_all_by_binary(self, service_get_all):
        db_service = fake_service.fake_db_service()
        service_get_all.return_value = [db_service]

        services = objects.ServiceList.get_all_by_binary(
            self.context, 'foo', 'bar')
        service_get_all.assert_called_once_with(
            self.context, binary='foo', disabled='bar')
        self.assertEqual(1, len(services))
        TestService._compare(self, db_service, services[0])
