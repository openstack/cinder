#    Copyright 2014 IBM Corp.
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

"""Unit tests for cinder.db.api."""


import datetime

import ddt
import enum
import mock
from mock import call
from oslo_config import cfg
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
from sqlalchemy.sql import operators

from cinder.api import common
from cinder import context
from cinder import db
from cinder.db.sqlalchemy import api as sqlalchemy_api
from cinder.db.sqlalchemy import models
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder import test
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import utils

CONF = cfg.CONF
THREE = 3
THREE_HUNDREDS = 300
ONE_HUNDREDS = 100
UTC_NOW = timeutils.utcnow()


def _quota_reserve(context, project_id):
    """Create sample Quota, QuotaUsage and Reservation objects.

    There is no method db.quota_usage_create(), so we have to use
    db.quota_reserve() for creating QuotaUsage objects.

    Returns reservations uuids.

    """
    def get_sync(resource, usage):
        def sync(elevated, project_id, session):
            return {resource: usage}
        return sync
    quotas = {}
    resources = {}
    deltas = {}
    for i, resource in enumerate(('volumes', 'gigabytes')):
        quota_obj = db.quota_create(context, project_id, resource, i + 1)
        quotas[resource] = quota_obj.hard_limit
        resources[resource] = quota.ReservableResource(resource,
                                                       '_sync_%s' % resource)
        deltas[resource] = i + 1
    return db.quota_reserve(
        context, resources, quotas, deltas,
        datetime.datetime.utcnow(), datetime.datetime.utcnow(),
        datetime.timedelta(days=1), project_id
    )


class BaseTest(test.TestCase, test.ModelsObjectComparatorMixin):
    def setUp(self):
        super(BaseTest, self).setUp()
        self.ctxt = context.get_admin_context()


@ddt.ddt
class DBCommonFilterTestCase(BaseTest):

    def setUp(self):
        super(DBCommonFilterTestCase, self).setUp()
        self.fake_volume = db.volume_create(self.ctxt,
                                            {'display_name': 'fake_name'})
        self.fake_group = utils.create_group(
            self.ctxt,
            group_type_id=fake.GROUP_TYPE_ID,
            volume_type_ids=[fake.VOLUME_TYPE_ID])

    @mock.patch('sqlalchemy.orm.query.Query.filter')
    def test__process_model_like_filter(self, mock_filter):
        filters = {'display_name': 'fake_name',
                   'display_description': 'fake_description',
                   'host': 123,
                   'status': []}
        session = sqlalchemy_api.get_session()
        query = session.query(models.Volume)
        mock_filter.return_value = query
        with mock.patch.object(operators.Operators, 'op') as mock_op:
            def fake_operator(value):
                return value
            mock_op.return_value = fake_operator
            sqlalchemy_api._process_model_like_filter(models.Volume,
                                                      query, filters)
            calls = [call('%fake_description%'),
                     call('%fake_name%'), call('%123%')]
            mock_filter.assert_has_calls(calls, any_order=True)

    @ddt.data({'handler': [db.volume_create, db.volume_get_all],
               'column': 'display_name',
               'resource': 'volume'},
              {'handler': [db.snapshot_create, db.snapshot_get_all],
               'column': 'display_name',
               'resource': 'snapshot'},
              {'handler': [db.message_create, db.message_get_all],
               'column': 'message_level',
               'resource': 'message'},
              {'handler': [db.backup_create, db.backup_get_all],
               'column': 'display_name',
               'resource': 'backup'},
              {'handler': [db.group_create, db.group_get_all],
               'column': 'name',
               'resource': 'group'},
              {'handler': [utils.create_group_snapshot,
                           db.group_snapshot_get_all],
               'column': 'name',
               'resource': 'group_snapshot'})
    @ddt.unpack
    def test_resource_get_all_like_filter(self, handler, column, resource):
        for index in ['001', '002']:
            option = {column: "fake_%s_%s" % (column, index)}
            if resource in ['snapshot', 'backup']:
                option['volume_id'] = self.fake_volume.id
            if resource in ['message']:
                option['project_id'] = fake.PROJECT_ID
                option['event_id'] = fake.UUID1
            if resource in ['group_snapshot']:
                handler[0](self.ctxt, self.fake_group.id,
                           name="fake_%s_%s" % (column, index))
            else:
                handler[0](self.ctxt, option)

        # test exact match
        exact_filter = {column: 'fake_%s' % column}
        resources = handler[1](self.ctxt, filters=exact_filter)
        self.assertEqual(0, len(resources))

        # test inexact match
        inexact_filter = {"%s~" % column: 'fake_%s' % column}
        resources = handler[1](self.ctxt, filters=inexact_filter)
        self.assertEqual(2, len(resources))


@ddt.ddt
class DBAPIServiceTestCase(BaseTest):

    """Unit tests for cinder.db.api.service_*."""

    def test_service_create(self):
        # Add a cluster value to the service
        values = {'cluster_name': 'cluster'}
        service = utils.create_service(self.ctxt, values)
        self.assertIsNotNone(service['id'])
        expected = utils.default_service_values()
        expected.update(values)
        for key, value in expected.items():
            self.assertEqual(value, service[key])

    def test_service_destroy(self):
        service1 = utils.create_service(self.ctxt, {})
        service2 = utils.create_service(self.ctxt, {'host': 'fake_host2'})

        self.assertDictEqual(
            {'deleted': True, 'deleted_at': mock.ANY},
            db.service_destroy(self.ctxt, service1['id']))
        self.assertRaises(exception.ServiceNotFound,
                          db.service_get, self.ctxt, service1['id'])
        self._assertEqualObjects(
            service2,
            db.service_get(self.ctxt, service2['id']))

    def test_service_update(self):
        service = utils.create_service(self.ctxt, {})
        new_values = {
            'host': 'fake_host1',
            'binary': 'fake_binary1',
            'topic': 'fake_topic1',
            'report_count': 4,
            'disabled': True
        }
        db.service_update(self.ctxt, service['id'], new_values)
        updated_service = db.service_get(self.ctxt, service['id'])
        for key, value in new_values.items():
            self.assertEqual(value, updated_service[key])

    def test_service_update_not_found_exception(self):
        self.assertRaises(exception.ServiceNotFound,
                          db.service_update, self.ctxt, 100500, {})

    def test_service_get(self):
        service1 = utils.create_service(self.ctxt, {})
        real_service1 = db.service_get(self.ctxt, service1['id'])
        self._assertEqualObjects(service1, real_service1)

    def test_service_get_by_cluster(self):
        service = utils.create_service(self.ctxt,
                                       {'cluster_name': 'cluster@backend'})
        # Search with an exact match
        real_service = db.service_get(self.ctxt,
                                      cluster_name='cluster@backend')
        self._assertEqualObjects(service, real_service)
        # Search without the backend
        real_service = db.service_get(self.ctxt, cluster_name='cluster')
        self._assertEqualObjects(service, real_service)

    def test_service_get_not_found_exception(self):
        self.assertRaises(exception.ServiceNotFound,
                          db.service_get, self.ctxt, 100500)

    def test_service_get_by_host_and_topic(self):
        service1 = utils.create_service(self.ctxt,
                                        {'host': 'host1', 'topic': 'topic1'})

        real_service1 = db.service_get(self.ctxt, host='host1', topic='topic1')
        self._assertEqualObjects(service1, real_service1)

    @ddt.data('disabled', 'frozen')
    def test_service_get_all_boolean_by_cluster(self, field_name):
        values = [
            # Enabled/Unfrozen services
            {'host': 'host1', 'binary': 'b1', field_name: False},
            {'host': 'host2', 'binary': 'b1', field_name: False,
             'cluster_name': 'enabled_unfrozen_cluster'},
            {'host': 'host3', 'binary': 'b1', field_name: True,
             'cluster_name': 'enabled_unfrozen_cluster'},

            # Disabled/Frozen services
            {'host': 'host4', 'binary': 'b1', field_name: True},
            {'host': 'host5', 'binary': 'b1', field_name: False,
             'cluster_name': 'disabled_frozen_cluster'},
            {'host': 'host6', 'binary': 'b1', field_name: True,
             'cluster_name': 'disabled_frozen_cluster'},
        ]

        db.cluster_create(self.ctxt, {'name': 'enabled_unfrozen_cluster',
                                      'binary': 'b1',
                                      field_name: False}),
        db.cluster_create(self.ctxt, {'name': 'disabled_frozen_cluster',
                                      'binary': 'b1',
                                      field_name: True}),
        services = [utils.create_service(self.ctxt, vals) for vals in values]

        false_services = db.service_get_all(self.ctxt, **{field_name: False})
        true_services = db.service_get_all(self.ctxt, **{field_name: True})

        self.assertSetEqual({s.host for s in services[:3]},
                            {s.host for s in false_services})
        self.assertSetEqual({s.host for s in services[3:]},
                            {s.host for s in true_services})

    def test_service_get_all(self):
        expired = (datetime.datetime.utcnow()
                   - datetime.timedelta(seconds=CONF.service_down_time + 1))
        db.cluster_create(self.ctxt, {'name': 'cluster_disabled',
                                      'binary': 'fake_binary',
                                      'disabled': True})
        db.cluster_create(self.ctxt, {'name': 'cluster_enabled',
                                      'binary': 'fake_binary',
                                      'disabled': False})
        values = [
            # Now we are updating updated_at at creation as well so this one
            # is up.
            {'host': 'host1', 'binary': 'b1', 'created_at': expired},
            {'host': 'host1@ceph', 'binary': 'b2'},
            {'host': 'host2', 'binary': 'b2'},
            {'disabled': False, 'cluster_name': 'cluster_enabled'},
            {'disabled': True, 'cluster_name': 'cluster_enabled'},
            {'disabled': False, 'cluster_name': 'cluster_disabled'},
            {'disabled': True, 'cluster_name': 'cluster_disabled'},
            {'disabled': True, 'created_at': expired, 'updated_at': expired},
        ]
        services = [utils.create_service(self.ctxt, vals) for vals in values]

        disabled_services = services[-3:]
        non_disabled_services = services[:-3]
        up_services = services[:7]
        down_services = [services[7]]
        expected = services[:2]
        expected_bin = services[1:3]
        compares = [
            (services, db.service_get_all(self.ctxt)),
            (expected, db.service_get_all(self.ctxt, host='host1')),
            (expected_bin, db.service_get_all(self.ctxt, binary='b2')),
            (disabled_services, db.service_get_all(self.ctxt, disabled=True)),
            (non_disabled_services, db.service_get_all(self.ctxt,
                                                       disabled=False)),
            (up_services, db.service_get_all(self.ctxt, is_up=True)),
            (down_services, db.service_get_all(self.ctxt, is_up=False)),
        ]
        for i, comp in enumerate(compares):
            self._assertEqualListsOfObjects(*comp,
                                            msg='Error comparing %s' % i)

    def test_service_get_all_by_topic(self):
        values = [
            {'host': 'host1', 'topic': 't1'},
            {'host': 'host2', 'topic': 't1'},
            {'host': 'host4', 'disabled': True, 'topic': 't1'},
            {'host': 'host3', 'topic': 't2'}
        ]
        services = [utils.create_service(self.ctxt, vals) for vals in values]
        expected = services[:3]
        real = db.service_get_all(self.ctxt, topic='t1')
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_all_by_binary(self):
        values = [
            {'host': 'host1', 'binary': 'b1'},
            {'host': 'host2', 'binary': 'b1'},
            {'host': 'host4', 'disabled': True, 'binary': 'b1'},
            {'host': 'host3', 'binary': 'b2'}
        ]
        services = [utils.create_service(self.ctxt, vals) for vals in values]
        expected = services[:3]
        real = db.service_get_all(self.ctxt, binary='b1')
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_by_args(self):
        values = [
            {'host': 'host1', 'binary': 'a'},
            {'host': 'host2', 'binary': 'b'}
        ]
        services = [utils.create_service(self.ctxt, vals) for vals in values]

        service1 = db.service_get(self.ctxt, host='host1', binary='a')
        self._assertEqualObjects(services[0], service1)

        service2 = db.service_get(self.ctxt, host='host2', binary='b')
        self._assertEqualObjects(services[1], service2)

    def test_service_get_all_by_cluster(self):
        values = [
            {'host': 'host1', 'cluster_name': 'cluster'},
            {'host': 'host2', 'cluster_name': 'cluster'},
            {'host': 'host3', 'cluster_name': 'cluster@backend'},
            {'host': 'host4', 'cluster_name': 'cluster2'},
        ]
        services = [utils.create_service(self.ctxt, vals) for vals in values]
        expected = services[:3]
        real = db.service_get_all(self.ctxt, cluster_name='cluster')
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_all_by_host_or_cluster(self):
        values = [
            {'host': 'host1', 'cluster_name': 'cluster'},
            {'host': 'host2', 'cluster_name': 'host1'},
            {'host': 'host3', 'cluster_name': 'cluster@backend'},
            {'host': 'host4', 'cluster_name': 'cluster2'},
        ]
        services = [utils.create_service(self.ctxt, vals) for vals in values]
        expected = services[0:2]
        real = db.service_get_all(self.ctxt, host_or_cluster='host1')
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_by_args_not_found_exception(self):
        self.assertRaises(exception.ServiceNotFound,
                          db.service_get,
                          self.ctxt, host='non-exists-host', binary='a')

    @mock.patch('sqlalchemy.orm.query.Query.filter_by')
    def test_service_get_by_args_with_case_insensitive(self, filter_by):
        CONF.set_default('connection', 'mysql://', 'database')
        db.service_get(self.ctxt, host='host', binary='a')

        self.assertNotEqual(0, filter_by.call_count)
        self.assertEqual(1, filter_by.return_value.filter.call_count)
        or_op = filter_by.return_value.filter.call_args[0][0].clauses[0]
        self.assertIsInstance(or_op,
                              sqlalchemy_api.sql.elements.BinaryExpression)
        binary_op = or_op.right
        self.assertIsInstance(binary_op, sqlalchemy_api.sql.functions.Function)
        self.assertEqual('binary', binary_op.name)


@ddt.ddt
class DBAPIVolumeTestCase(BaseTest):

    """Unit tests for cinder.db.api.volume_*."""

    def test_volume_create(self):
        volume = db.volume_create(self.ctxt, {'host': 'host1'})
        self.assertTrue(uuidutils.is_uuid_like(volume['id']))
        self.assertEqual('host1', volume.host)

    def test_volume_attached_invalid_uuid(self):
        self.assertRaises(exception.InvalidUUID, db.volume_attached, self.ctxt,
                          42, 'invalid-uuid', None, '/tmp')

    def test_volume_attached_to_instance(self):
        volume = db.volume_create(self.ctxt, {'host': 'host1'})
        instance_uuid = fake.INSTANCE_ID
        values = {'volume_id': volume['id'],
                  'instance_uuid': instance_uuid,
                  'attach_status': fields.VolumeAttachStatus.ATTACHING, }
        attachment = db.volume_attach(self.ctxt, values)
        volume_db, updated_values = db.volume_attached(
            self.ctxt,
            attachment['id'],
            instance_uuid, None, '/tmp')
        expected_updated_values = {
            'mountpoint': '/tmp',
            'attach_status': fields.VolumeAttachStatus.ATTACHED,
            'instance_uuid': instance_uuid,
            'attached_host': None,
            'attach_time': mock.ANY,
            'attach_mode': 'rw'}
        self.assertDictEqual(expected_updated_values, updated_values)

        volume = db.volume_get(self.ctxt, volume['id'])
        attachment = db.volume_attachment_get(self.ctxt, attachment['id'])
        self._assertEqualObjects(volume, volume_db,
                                 ignored_keys='volume_attachment')
        self._assertEqualListsOfObjects(volume.volume_attachment,
                                        volume_db.volume_attachment, 'volume')
        self.assertEqual('in-use', volume['status'])
        self.assertEqual('/tmp', attachment['mountpoint'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertEqual(instance_uuid, attachment['instance_uuid'])
        self.assertIsNone(attachment['attached_host'])
        self.assertEqual(volume.project_id, attachment['volume']['project_id'])

    def test_volume_attached_to_host(self):
        volume = db.volume_create(self.ctxt, {'host': 'host1'})
        host_name = 'fake_host'
        values = {'volume_id': volume['id'],
                  'attached_host': host_name,
                  'attach_status': fields.VolumeAttachStatus.ATTACHING, }
        attachment = db.volume_attach(self.ctxt, values)
        volume_db, updated_values = db.volume_attached(
            self.ctxt, attachment['id'],
            None, host_name, '/tmp')
        expected_updated_values = {
            'mountpoint': '/tmp',
            'attach_status': fields.VolumeAttachStatus.ATTACHED,
            'instance_uuid': None,
            'attached_host': host_name,
            'attach_time': mock.ANY,
            'attach_mode': 'rw'}
        self.assertDictEqual(expected_updated_values, updated_values)
        volume = db.volume_get(self.ctxt, volume['id'])
        self._assertEqualObjects(volume, volume_db,
                                 ignored_keys='volume_attachment')
        self._assertEqualListsOfObjects(volume.volume_attachment,
                                        volume_db.volume_attachment, 'volume')
        attachment = db.volume_attachment_get(self.ctxt, attachment['id'])
        self.assertEqual('in-use', volume['status'])
        self.assertEqual('/tmp', attachment['mountpoint'])
        self.assertEqual(fields.VolumeAttachStatus.ATTACHED,
                         attachment['attach_status'])
        self.assertIsNone(attachment['instance_uuid'])
        self.assertEqual(attachment['attached_host'], host_name)
        self.assertEqual(volume.project_id, attachment['volume']['project_id'])

    def test_volume_data_get_for_host(self):
        for i in range(THREE):
            for j in range(THREE):
                db.volume_create(self.ctxt, {'host': 'h%d' % i,
                                             'size': ONE_HUNDREDS})
        for i in range(THREE):
            self.assertEqual((THREE, THREE_HUNDREDS),
                             db.volume_data_get_for_host(
                                 self.ctxt, 'h%d' % i))

    def test_volume_data_get_for_host_for_multi_backend(self):
        for i in range(THREE):
            for j in range(THREE):
                db.volume_create(self.ctxt, {'host':
                                             'h%d@lvmdriver-1#lvmdriver-1' % i,
                                             'size': ONE_HUNDREDS})
        for i in range(THREE):
            self.assertEqual((THREE, THREE_HUNDREDS),
                             db.volume_data_get_for_host(
                                 self.ctxt, 'h%d@lvmdriver-1' % i))

    def test_volume_data_get_for_project(self):
        for i in range(THREE):
            for j in range(THREE):
                db.volume_create(self.ctxt, {'project_id': 'p%d' % i,
                                             'size': ONE_HUNDREDS,
                                             'host': 'h-%d-%d' % (i, j),
                                             })
        for i in range(THREE):
            self.assertEqual((THREE, THREE_HUNDREDS),
                             db.volume_data_get_for_project(
                                 self.ctxt, 'p%d' % i))

    def test_volume_detached_from_instance(self):
        volume = db.volume_create(self.ctxt, {})
        instance_uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        values = {'volume_id': volume['id'],
                  'instance_uuid': instance_uuid,
                  'attach_status': fields.VolumeAttachStatus.ATTACHING, }
        attachment = db.volume_attach(self.ctxt, values)
        db.volume_attached(self.ctxt, attachment.id,
                           instance_uuid,
                           None, '/tmp')
        volume_updates, attachment_updates = (
            db.volume_detached(self.ctxt, volume.id, attachment.id))
        expected_attachment = {
            'attach_status': fields.VolumeAttachStatus.DETACHED,
            'detach_time': mock.ANY,
            'deleted': True,
            'deleted_at': mock.ANY, }
        self.assertDictEqual(expected_attachment, attachment_updates)
        expected_volume = {
            'status': 'available',
            'attach_status': fields.VolumeAttachStatus.DETACHED, }
        self.assertDictEqual(expected_volume, volume_updates)
        volume = db.volume_get(self.ctxt, volume.id)
        self.assertRaises(exception.VolumeAttachmentNotFound,
                          db.volume_attachment_get,
                          self.ctxt,
                          attachment.id)
        self.assertEqual('available', volume.status)

    def test_volume_detached_two_attachments(self):
        volume = db.volume_create(self.ctxt, {})
        instance_uuid = fake.INSTANCE_ID
        values = {'volume_id': volume.id,
                  'instance_uuid': instance_uuid,
                  'attach_status': fields.VolumeAttachStatus.ATTACHING, }
        attachment = db.volume_attach(self.ctxt, values)
        values2 = {'volume_id': volume.id,
                   'instance_uuid': fake.OBJECT_ID,
                   'attach_status': fields.VolumeAttachStatus.ATTACHING, }
        db.volume_attach(self.ctxt, values2)
        db.volume_attached(self.ctxt, attachment.id,
                           instance_uuid,
                           None, '/tmp')
        volume_updates, attachment_updates = (
            db.volume_detached(self.ctxt, volume.id, attachment.id))
        expected_attachment = {
            'attach_status': fields.VolumeAttachStatus.DETACHED,
            'detach_time': mock.ANY,
            'deleted': True,
            'deleted_at': mock.ANY, }
        self.assertDictEqual(expected_attachment, attachment_updates)
        expected_volume = {
            'status': 'in-use',
            'attach_status': fields.VolumeAttachStatus.ATTACHED, }
        self.assertDictEqual(expected_volume, volume_updates)
        volume = db.volume_get(self.ctxt, volume.id)
        self.assertRaises(exception.VolumeAttachmentNotFound,
                          db.volume_attachment_get,
                          self.ctxt,
                          attachment.id)
        self.assertEqual('in-use', volume.status)

    def test_volume_detached_invalid_attachment(self):
        volume = db.volume_create(self.ctxt, {})
        # detach it again
        volume_updates, attachment_updates = (
            db.volume_detached(self.ctxt, volume.id, fake.ATTACHMENT_ID))
        self.assertIsNone(attachment_updates)
        expected_volume = {
            'status': 'available',
            'attach_status': fields.VolumeAttachStatus.DETACHED, }
        self.assertDictEqual(expected_volume, volume_updates)
        volume = db.volume_get(self.ctxt, volume.id)
        self.assertEqual('available', volume.status)

    def test_volume_detached_from_host(self):
        volume = db.volume_create(self.ctxt, {})
        host_name = 'fake_host'
        values = {'volume_id': volume.id,
                  'attach_host': host_name,
                  'attach_status': fields.VolumeAttachStatus.ATTACHING, }
        attachment = db.volume_attach(self.ctxt, values)
        db.volume_attached(self.ctxt, attachment.id,
                           None, host_name, '/tmp')
        volume_updates, attachment_updates = (
            db.volume_detached(self.ctxt, volume.id, attachment.id))
        expected_attachment = {
            'attach_status': fields.VolumeAttachStatus.DETACHED,
            'detach_time': mock.ANY,
            'deleted': True,
            'deleted_at': mock.ANY}
        self.assertDictEqual(expected_attachment, attachment_updates)
        expected_volume = {
            'status': 'available',
            'attach_status': fields.VolumeAttachStatus.DETACHED, }
        self.assertDictEqual(expected_volume, volume_updates)
        volume = db.volume_get(self.ctxt, volume.id)
        self.assertRaises(exception.VolumeAttachmentNotFound,
                          db.volume_attachment_get,
                          self.ctxt,
                          attachment.id)
        self.assertEqual('available', volume.status)

    def test_volume_get(self):
        volume = db.volume_create(self.ctxt, {})
        self._assertEqualObjects(volume, db.volume_get(self.ctxt,
                                                       volume['id']))

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=UTC_NOW)
    def test_volume_destroy(self, utcnow_mock):
        volume = db.volume_create(self.ctxt, {})
        self.assertDictEqual(
            {'status': 'deleted', 'deleted': True, 'deleted_at': UTC_NOW,
             'migration_status': None},
            db.volume_destroy(self.ctxt, volume['id']))
        self.assertRaises(exception.VolumeNotFound, db.volume_get,
                          self.ctxt, volume['id'])

    def test_volume_get_all(self):
        volumes = [db.volume_create(self.ctxt,
                   {'host': 'h%d' % i, 'size': i})
                   for i in range(3)]
        self._assertEqualListsOfObjects(volumes, db.volume_get_all(
                                        self.ctxt, None, None, ['host'], None))

    @ddt.data('cluster_name', 'host')
    def test_volume_get_all_filter_host_and_cluster(self, field):
        volumes = []
        for i in range(2):
            for value in ('host%d@backend#pool', 'host%d@backend', 'host%d'):
                kwargs = {field: value % i}
                volumes.append(utils.create_volume(self.ctxt, **kwargs))

        for i in range(3):
            filters = {field: getattr(volumes[i], field)}
            result = db.volume_get_all(self.ctxt, filters=filters)
            self.assertEqual(i + 1, len(result))
            self.assertSetEqual({v.id for v in volumes[:i + 1]},
                                {v.id for v in result})

    def test_volume_get_all_marker_passed(self):
        volumes = [
            db.volume_create(self.ctxt, {'id': 1}),
            db.volume_create(self.ctxt, {'id': 2}),
            db.volume_create(self.ctxt, {'id': 3}),
            db.volume_create(self.ctxt, {'id': 4}),
        ]

        self._assertEqualListsOfObjects(volumes[2:], db.volume_get_all(
                                        self.ctxt, 2, 2, ['id'], ['asc']))

    def test_volume_get_all_by_host(self):
        volumes = []
        for i in range(3):
            volumes.append([db.volume_create(self.ctxt, {'host': 'h%d' % i})
                            for j in range(3)])
        for i in range(3):
            self._assertEqualListsOfObjects(volumes[i],
                                            db.volume_get_all_by_host(
                                            self.ctxt, 'h%d' % i))

    def test_volume_get_all_by_host_with_pools(self):
        volumes = []
        vol_on_host_wo_pool = [db.volume_create(self.ctxt, {'host': 'foo'})
                               for j in range(3)]
        vol_on_host_w_pool = [db.volume_create(
            self.ctxt, {'host': 'foo#pool0'})]
        volumes.append((vol_on_host_wo_pool +
                        vol_on_host_w_pool))
        # insert an additional record that doesn't belongs to the same
        # host as 'foo' and test if it is included in the result
        db.volume_create(self.ctxt, {'host': 'foobar'})
        self._assertEqualListsOfObjects(volumes[0],
                                        db.volume_get_all_by_host(
                                        self.ctxt, 'foo'))

    def test_volume_get_all_by_host_with_filters(self):
        v1 = db.volume_create(self.ctxt, {'host': 'h1', 'display_name': 'v1',
                                          'status': 'available'})
        v2 = db.volume_create(self.ctxt, {'host': 'h1', 'display_name': 'v2',
                                          'status': 'available'})
        v3 = db.volume_create(self.ctxt, {'host': 'h2', 'display_name': 'v1',
                                          'status': 'available'})
        self._assertEqualListsOfObjects(
            [v1],
            db.volume_get_all_by_host(self.ctxt, 'h1',
                                      filters={'display_name': 'v1'}))
        self._assertEqualListsOfObjects(
            [v1, v2],
            db.volume_get_all_by_host(
                self.ctxt, 'h1',
                filters={'display_name': ['v1', 'v2', 'foo']}))
        self._assertEqualListsOfObjects(
            [v1, v2],
            db.volume_get_all_by_host(self.ctxt, 'h1',
                                      filters={'status': 'available'}))
        self._assertEqualListsOfObjects(
            [v3],
            db.volume_get_all_by_host(self.ctxt, 'h2',
                                      filters={'display_name': 'v1'}))
        # No match
        vols = db.volume_get_all_by_host(self.ctxt, 'h1',
                                         filters={'status': 'foo'})
        self.assertEqual([], vols)
        # Bogus filter, should return empty list
        vols = db.volume_get_all_by_host(self.ctxt, 'h1',
                                         filters={'foo': 'bar'})
        self.assertEqual([], vols)

    def test_volume_get_all_by_group(self):
        volumes = []
        for i in range(3):
            volumes.append([db.volume_create(self.ctxt, {
                'consistencygroup_id': 'g%d' % i}) for j in range(3)])
        for i in range(3):
            self._assertEqualListsOfObjects(volumes[i],
                                            db.volume_get_all_by_group(
                                            self.ctxt, 'g%d' % i))

    def test_volume_get_all_by_group_with_filters(self):
        v1 = db.volume_create(self.ctxt, {'consistencygroup_id': 'g1',
                                          'display_name': 'v1'})
        v2 = db.volume_create(self.ctxt, {'consistencygroup_id': 'g1',
                                          'display_name': 'v2'})
        v3 = db.volume_create(self.ctxt, {'consistencygroup_id': 'g2',
                                          'display_name': 'v1'})
        self._assertEqualListsOfObjects(
            [v1],
            db.volume_get_all_by_group(self.ctxt, 'g1',
                                       filters={'display_name': 'v1'}))
        self._assertEqualListsOfObjects(
            [v1, v2],
            db.volume_get_all_by_group(self.ctxt, 'g1',
                                       filters={'display_name': ['v1', 'v2']}))
        self._assertEqualListsOfObjects(
            [v3],
            db.volume_get_all_by_group(self.ctxt, 'g2',
                                       filters={'display_name': 'v1'}))
        # No match
        vols = db.volume_get_all_by_group(self.ctxt, 'g1',
                                          filters={'display_name': 'foo'})
        self.assertEqual([], vols)
        # Bogus filter, should return empty list
        vols = db.volume_get_all_by_group(self.ctxt, 'g1',
                                          filters={'foo': 'bar'})
        self.assertEqual([], vols)

    def test_volume_get_all_by_project(self):
        volumes = []
        for i in range(3):
            volumes.append([db.volume_create(self.ctxt, {
                'project_id': 'p%d' % i}) for j in range(3)])
        for i in range(3):
            self._assertEqualListsOfObjects(volumes[i],
                                            db.volume_get_all_by_project(
                                            self.ctxt, 'p%d' % i, None,
                                            None, ['host'], None))

    def test_volume_get_by_name(self):
        db.volume_create(self.ctxt, {'display_name': 'vol1'})
        db.volume_create(self.ctxt, {'display_name': 'vol2'})
        db.volume_create(self.ctxt, {'display_name': 'vol3'})

        # no name filter
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['asc'])
        self.assertEqual(3, len(volumes))
        # filter on name
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['asc'], {'display_name': 'vol2'})
        self.assertEqual(1, len(volumes))
        self.assertEqual('vol2', volumes[0]['display_name'])
        # filter no match
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['asc'], {'display_name': 'vol4'})
        self.assertEqual(0, len(volumes))

    def test_volume_list_by_status(self):
        db.volume_create(self.ctxt, {'display_name': 'vol1',
                                     'status': 'available'})
        db.volume_create(self.ctxt, {'display_name': 'vol2',
                                     'status': 'available'})
        db.volume_create(self.ctxt, {'display_name': 'vol3',
                                     'status': 'in-use'})

        # no status filter
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['asc'])
        self.assertEqual(3, len(volumes))
        # single match
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['asc'], {'status': 'in-use'})
        self.assertEqual(1, len(volumes))
        self.assertEqual('in-use', volumes[0]['status'])
        # multiple match
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['asc'], {'status': 'available'})
        self.assertEqual(2, len(volumes))
        for volume in volumes:
            self.assertEqual('available', volume['status'])
        # multiple filters
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['asc'], {'status': 'available',
                                              'display_name': 'vol1'})
        self.assertEqual(1, len(volumes))
        self.assertEqual('vol1', volumes[0]['display_name'])
        self.assertEqual('available', volumes[0]['status'])
        # no match
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['asc'], {'status': 'in-use',
                                              'display_name': 'vol1'})
        self.assertEqual(0, len(volumes))

    def _assertEqualsVolumeOrderResult(self, correct_order, limit=None,
                                       sort_keys=None, sort_dirs=None,
                                       filters=None, project_id=None,
                                       marker=None,
                                       match_keys=['id', 'display_name',
                                                   'volume_metadata',
                                                   'created_at']):
        """Verifies that volumes are returned in the correct order."""
        if project_id:
            result = db.volume_get_all_by_project(self.ctxt, project_id,
                                                  marker, limit,
                                                  sort_keys=sort_keys,
                                                  sort_dirs=sort_dirs,
                                                  filters=filters)
        else:
            result = db.volume_get_all(self.ctxt, marker, limit,
                                       sort_keys=sort_keys,
                                       sort_dirs=sort_dirs,
                                       filters=filters)
        self.assertEqual(len(correct_order), len(result))
        for vol1, vol2 in zip(result, correct_order):
            for key in match_keys:
                val1 = vol1.get(key)
                val2 = vol2.get(key)
                # metadata is a dict, compare the 'key' and 'value' of each
                if key == 'volume_metadata':
                    self.assertEqual(len(val1), len(val2))
                    val1_dict = {x.key: x.value for x in val1}
                    val2_dict = {x.key: x.value for x in val2}
                    self.assertDictEqual(val1_dict, val2_dict)
                else:
                    self.assertEqual(val1, val2)
        return result

    def test_volume_get_by_filter(self):
        """Verifies that all filtering is done at the DB layer."""
        vols = []
        vols.extend([db.volume_create(self.ctxt,
                                      {'project_id': 'g1',
                                       'display_name': 'name_%d' % i,
                                       'size': 1})
                     for i in range(2)])
        vols.extend([db.volume_create(self.ctxt,
                                      {'project_id': 'g1',
                                       'display_name': 'name_%d' % i,
                                       'size': 2})
                     for i in range(2)])
        vols.extend([db.volume_create(self.ctxt,
                                      {'project_id': 'g1',
                                       'display_name': 'name_%d' % i})
                     for i in range(2)])
        vols.extend([db.volume_create(self.ctxt,
                                      {'project_id': 'g2',
                                       'display_name': 'name_%d' % i,
                                       'size': 1})
                     for i in range(2)])

        # By project, filter on size and name
        filters = {'size': '1'}
        correct_order = [vols[1], vols[0]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            project_id='g1')
        filters = {'size': '1', 'display_name': 'name_1'}
        correct_order = [vols[1]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            project_id='g1')

        # Remove project scope
        filters = {'size': '1'}
        correct_order = [vols[7], vols[6], vols[1], vols[0]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters)
        filters = {'size': '1', 'display_name': 'name_1'}
        correct_order = [vols[7], vols[1]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters)

        # Remove size constraint
        filters = {'display_name': 'name_1'}
        correct_order = [vols[5], vols[3], vols[1]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            project_id='g1')
        correct_order = [vols[7], vols[5], vols[3], vols[1]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters)

        # Verify bogus values return nothing
        filters = {'display_name': 'name_1', 'bogus_value': 'foo'}
        self._assertEqualsVolumeOrderResult([], filters=filters,
                                            project_id='g1')
        self._assertEqualsVolumeOrderResult([], project_id='bogus')
        self._assertEqualsVolumeOrderResult([], filters=filters)
        self._assertEqualsVolumeOrderResult([], filters={'metadata':
                                                         'not valid'})
        self._assertEqualsVolumeOrderResult([], filters={'metadata':
                                                         ['not', 'valid']})

        # Verify that relationship property keys return nothing, these
        # exist on the Volumes model but are not columns
        filters = {'volume_type': 'bogus_type'}
        self._assertEqualsVolumeOrderResult([], filters=filters)

    def test_volume_get_all_filters_limit(self):
        vol1 = db.volume_create(self.ctxt, {'display_name': 'test1'})
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2'})
        vol3 = db.volume_create(self.ctxt, {'display_name': 'test2',
                                            'metadata': {'key1': 'val1'}})
        vol4 = db.volume_create(self.ctxt, {'display_name': 'test3',
                                            'metadata': {'key1': 'val1',
                                                         'key2': 'val2'}})
        vol5 = db.volume_create(self.ctxt, {'display_name': 'test3',
                                            'metadata': {'key2': 'val2',
                                                         'key3': 'val3'},
                                            'host': 'host5'})
        db.volume_admin_metadata_update(self.ctxt, vol5.id,
                                        {"readonly": "True"}, False)

        vols = [vol5, vol4, vol3, vol2, vol1]

        # Ensure we have 5 total instances
        self._assertEqualsVolumeOrderResult(vols)

        # No filters, test limit
        self._assertEqualsVolumeOrderResult(vols[:1], limit=1)
        self._assertEqualsVolumeOrderResult(vols[:4], limit=4)

        # Just the test2 volumes
        filters = {'display_name': 'test2'}
        self._assertEqualsVolumeOrderResult([vol3, vol2], filters=filters)
        self._assertEqualsVolumeOrderResult([vol3], limit=1,
                                            filters=filters)
        self._assertEqualsVolumeOrderResult([vol3, vol2], limit=2,
                                            filters=filters)
        self._assertEqualsVolumeOrderResult([vol3, vol2], limit=100,
                                            filters=filters)

        # metadata filters
        filters = {'metadata': {'key1': 'val1'}}
        self._assertEqualsVolumeOrderResult([vol4, vol3], filters=filters)
        self._assertEqualsVolumeOrderResult([vol4], limit=1,
                                            filters=filters)
        self._assertEqualsVolumeOrderResult([vol4, vol3], limit=10,
                                            filters=filters)

        filters = {'metadata': {'readonly': 'True'}}
        self._assertEqualsVolumeOrderResult([vol5], filters=filters)

        filters = {'metadata': {'key1': 'val1',
                                'key2': 'val2'}}
        self._assertEqualsVolumeOrderResult([vol4], filters=filters)
        self._assertEqualsVolumeOrderResult([vol4], limit=1,
                                            filters=filters)

        # No match
        filters = {'metadata': {'key1': 'val1',
                                'key2': 'val2',
                                'key3': 'val3'}}
        self._assertEqualsVolumeOrderResult([], filters=filters)
        filters = {'metadata': {'key1': 'val1',
                                'key2': 'bogus'}}
        self._assertEqualsVolumeOrderResult([], filters=filters)
        filters = {'metadata': {'key1': 'val1',
                                'key2': 'val1'}}
        self._assertEqualsVolumeOrderResult([], filters=filters)

        # Combination
        filters = {'display_name': 'test2',
                   'metadata': {'key1': 'val1'}}
        self._assertEqualsVolumeOrderResult([vol3], filters=filters)
        self._assertEqualsVolumeOrderResult([vol3], limit=1,
                                            filters=filters)
        self._assertEqualsVolumeOrderResult([vol3], limit=100,
                                            filters=filters)
        filters = {'display_name': 'test3',
                   'metadata': {'key2': 'val2',
                                'key3': 'val3'},
                   'host': 'host5'}
        self._assertEqualsVolumeOrderResult([vol5], filters=filters)
        self._assertEqualsVolumeOrderResult([vol5], limit=1,
                                            filters=filters)

    def test_volume_get_no_migration_targets(self):
        """Verifies the unique 'no_migration_targets'=True filter.

        This filter returns volumes with either a NULL 'migration_status'
        or a non-NULL value that does not start with 'target:'.
        """
        vol1 = db.volume_create(self.ctxt, {'display_name': 'test1'})
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2',
                                            'migration_status': 'bogus'})
        vol3 = db.volume_create(self.ctxt, {'display_name': 'test3',
                                            'migration_status': 'btarget:'})
        vol4 = db.volume_create(self.ctxt, {'display_name': 'test4',
                                            'migration_status': 'target:'})

        # Ensure we have 4 total instances, default sort of created_at (desc)
        self._assertEqualsVolumeOrderResult([vol4, vol3, vol2, vol1])

        # Apply the unique filter
        filters = {'no_migration_targets': True}
        self._assertEqualsVolumeOrderResult([vol3, vol2, vol1],
                                            filters=filters)
        self._assertEqualsVolumeOrderResult([vol3, vol2], limit=2,
                                            filters=filters)

        filters = {'no_migration_targets': True,
                   'display_name': 'test4'}
        self._assertEqualsVolumeOrderResult([], filters=filters)

    def test_volume_get_all_by_filters_sort_keys(self):
        # Volumes that will reply to the query
        test_h1_avail = db.volume_create(self.ctxt, {'display_name': 'test',
                                                     'status': 'available',
                                                     'host': 'h1'})
        test_h1_error = db.volume_create(self.ctxt, {'display_name': 'test',
                                                     'status': 'error',
                                                     'host': 'h1'})
        test_h1_error2 = db.volume_create(self.ctxt, {'display_name': 'test',
                                                      'status': 'error',
                                                      'host': 'h1'})
        test_h2_avail = db.volume_create(self.ctxt, {'display_name': 'test',
                                                     'status': 'available',
                                                     'host': 'h2'})
        test_h2_error = db.volume_create(self.ctxt, {'display_name': 'test',
                                                     'status': 'error',
                                                     'host': 'h2'})
        test_h2_error2 = db.volume_create(self.ctxt, {'display_name': 'test',
                                                      'status': 'error',
                                                      'host': 'h2'})
        # Other volumes in the DB, will not match name filter
        other_error = db.volume_create(self.ctxt, {'display_name': 'other',
                                                   'status': 'error',
                                                   'host': 'a'})
        other_active = db.volume_create(self.ctxt, {'display_name': 'other',
                                                    'status': 'available',
                                                    'host': 'a'})
        filters = {'display_name': 'test'}

        # Verify different sort key/direction combinations
        sort_keys = ['host', 'status', 'created_at']
        sort_dirs = ['asc', 'asc', 'asc']
        correct_order = [test_h1_avail, test_h1_error, test_h1_error2,
                         test_h2_avail, test_h2_error, test_h2_error2]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            sort_keys=sort_keys,
                                            sort_dirs=sort_dirs)

        sort_dirs = ['asc', 'desc', 'asc']
        correct_order = [test_h1_error, test_h1_error2, test_h1_avail,
                         test_h2_error, test_h2_error2, test_h2_avail]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            sort_keys=sort_keys,
                                            sort_dirs=sort_dirs)

        sort_dirs = ['desc', 'desc', 'asc']
        correct_order = [test_h2_error, test_h2_error2, test_h2_avail,
                         test_h1_error, test_h1_error2, test_h1_avail]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            sort_keys=sort_keys,
                                            sort_dirs=sort_dirs)

        # created_at is added by default if not supplied, descending order
        sort_keys = ['host', 'status']
        sort_dirs = ['desc', 'desc']
        correct_order = [test_h2_error2, test_h2_error, test_h2_avail,
                         test_h1_error2, test_h1_error, test_h1_avail]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            sort_keys=sort_keys,
                                            sort_dirs=sort_dirs)

        sort_dirs = ['asc', 'asc']
        correct_order = [test_h1_avail, test_h1_error, test_h1_error2,
                         test_h2_avail, test_h2_error, test_h2_error2]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            sort_keys=sort_keys,
                                            sort_dirs=sort_dirs)

        # Remove name filter
        correct_order = [other_active, other_error,
                         test_h1_avail, test_h1_error, test_h1_error2,
                         test_h2_avail, test_h2_error, test_h2_error2]
        self._assertEqualsVolumeOrderResult(correct_order, sort_keys=sort_keys,
                                            sort_dirs=sort_dirs)

        # No sort data, default sort of created_at, id (desc)
        correct_order = [other_active, other_error,
                         test_h2_error2, test_h2_error, test_h2_avail,
                         test_h1_error2, test_h1_error, test_h1_avail]
        self._assertEqualsVolumeOrderResult(correct_order)

    def test_volume_get_all_by_filters_sort_keys_paginate(self):
        """Verifies sort order with pagination."""
        # Volumes that will reply to the query
        test1_avail = db.volume_create(self.ctxt, {'display_name': 'test',
                                                   'size': 1,
                                                   'status': 'available'})
        test1_error = db.volume_create(self.ctxt, {'display_name': 'test',
                                                   'size': 1,
                                                   'status': 'error'})
        test1_error2 = db.volume_create(self.ctxt, {'display_name': 'test',
                                                    'size': 1,
                                                    'status': 'error'})
        test2_avail = db.volume_create(self.ctxt, {'display_name': 'test',
                                                   'size': 2,
                                                   'status': 'available'})
        test2_error = db.volume_create(self.ctxt, {'display_name': 'test',
                                                   'size': 2,
                                                   'status': 'error'})
        test2_error2 = db.volume_create(self.ctxt, {'display_name': 'test',
                                                    'size': 2,
                                                    'status': 'error'})

        # Other volumes in the DB, will not match name filter
        db.volume_create(self.ctxt, {'display_name': 'other'})
        db.volume_create(self.ctxt, {'display_name': 'other'})
        filters = {'display_name': 'test'}
        # Common sort information for every query
        sort_keys = ['size', 'status', 'created_at']
        sort_dirs = ['asc', 'desc', 'asc']
        # Overall correct volume order based on the sort keys
        correct_order = [test1_error, test1_error2, test1_avail,
                         test2_error, test2_error2, test2_avail]

        # Limits of 1, 2, and 3, verify that the volumes returned are in the
        # correct sorted order, update the marker to get the next correct page
        for limit in range(1, 4):
            marker = None
            # Include the maximum number of volumes (ie, 6) to ensure that
            # the last query (with marker pointing to the last volume)
            # returns 0 servers
            for i in range(0, 7, limit):
                if i == len(correct_order):
                    correct = []
                else:
                    correct = correct_order[i:i + limit]
                vols = self._assertEqualsVolumeOrderResult(
                    correct, filters=filters,
                    sort_keys=sort_keys, sort_dirs=sort_dirs,
                    limit=limit, marker=marker)
                if correct:
                    marker = vols[-1]['id']
                    self.assertEqual(correct[-1]['id'], marker)

    def test_volume_get_all_invalid_sort_key(self):
        for keys in (['foo'], ['display_name', 'foo']):
            self.assertRaises(exception.InvalidInput, db.volume_get_all,
                              self.ctxt, None, None, sort_keys=keys)

    def test_volume_update(self):
        volume = db.volume_create(self.ctxt, {'host': 'h1'})
        db.volume_update(self.ctxt, volume.id,
                         {'host': 'h2',
                          'metadata': {'m1': 'v1'}})
        volume = db.volume_get(self.ctxt, volume.id)
        self.assertEqual('h2', volume.host)
        self.assertEqual(1, len(volume.volume_metadata))
        db_metadata = volume.volume_metadata[0]
        self.assertEqual('m1', db_metadata.key)
        self.assertEqual('v1', db_metadata.value)

    def test_volume_update_nonexistent(self):
        self.assertRaises(exception.VolumeNotFound, db.volume_update,
                          self.ctxt, 42, {})

    def test_volume_metadata_get(self):
        metadata = {'a': 'b', 'c': 'd'}
        db.volume_create(self.ctxt, {'id': 1, 'metadata': metadata})

        self.assertEqual(metadata, db.volume_metadata_get(self.ctxt, 1))

    def test_volume_metadata_update(self):
        metadata1 = {'a': '1', 'c': '2'}
        metadata2 = {'a': '3', 'd': '5'}
        should_be = {'a': '3', 'c': '2', 'd': '5'}

        db.volume_create(self.ctxt, {'id': 1, 'metadata': metadata1})
        db_meta = db.volume_metadata_update(self.ctxt, 1, metadata2, False)

        self.assertEqual(should_be, db_meta)

    @mock.patch.object(db.sqlalchemy.api,
                       '_volume_glance_metadata_key_to_id',
                       return_value = '1')
    def test_volume_glance_metadata_key_to_id_called(self,
                                                     metadata_key_to_id_mock):
        image_metadata = {'abc': '123'}

        # create volume with metadata.
        db.volume_create(self.ctxt, {'id': 1,
                                     'metadata': image_metadata})

        # delete metadata associated with the volume.
        db.volume_metadata_delete(self.ctxt,
                                  1,
                                  'abc',
                                  meta_type=common.METADATA_TYPES.image)

        # assert _volume_glance_metadata_key_to_id() was called exactly once
        metadata_key_to_id_mock.assert_called_once_with(self.ctxt, 1, 'abc')

    def test_case_sensitive_glance_metadata_delete(self):
        user_metadata = {'a': '1', 'c': '2'}
        image_metadata = {'abc': '123', 'ABC': '123'}

        # create volume with metadata.
        db.volume_create(self.ctxt, {'id': 1,
                                     'metadata': user_metadata})

        # delete user metadata associated with the volume.
        db.volume_metadata_delete(self.ctxt, 1, 'c',
                                  meta_type=common.METADATA_TYPES.user)
        user_metadata.pop('c')

        self.assertEqual(user_metadata,
                         db.volume_metadata_get(self.ctxt, 1))

        # create image metadata associated with the volume.
        db.volume_metadata_update(
            self.ctxt,
            1,
            image_metadata,
            False,
            meta_type=common.METADATA_TYPES.image)

        # delete image metadata associated with the volume.
        db.volume_metadata_delete(
            self.ctxt,
            1,
            'abc',
            meta_type=common.METADATA_TYPES.image)

        image_metadata.pop('abc')

        # parse the result to build the dict.
        rows = db.volume_glance_metadata_get(self.ctxt, 1)
        result = {}
        for row in rows:
            result[row['key']] = row['value']
        self.assertEqual(image_metadata, result)

    def test_volume_metadata_update_with_metatype(self):
        user_metadata1 = {'a': '1', 'c': '2'}
        user_metadata2 = {'a': '3', 'd': '5'}
        expected1 = {'a': '3', 'c': '2', 'd': '5'}
        image_metadata1 = {'e': '1', 'f': '2'}
        image_metadata2 = {'e': '3', 'g': '5'}
        expected2 = {'e': '3', 'f': '2', 'g': '5'}
        FAKE_METADATA_TYPE = enum.Enum('METADATA_TYPES', 'fake_type')

        db.volume_create(self.ctxt, {'id': 1, 'metadata': user_metadata1})

        # update user metatdata associated with volume.
        db_meta = db.volume_metadata_update(
            self.ctxt,
            1,
            user_metadata2,
            False,
            meta_type=common.METADATA_TYPES.user)
        self.assertEqual(expected1, db_meta)

        # create image metatdata associated with volume.
        db_meta = db.volume_metadata_update(
            self.ctxt,
            1,
            image_metadata1,
            False,
            meta_type=common.METADATA_TYPES.image)
        self.assertEqual(image_metadata1, db_meta)

        # update image metatdata associated with volume.
        db_meta = db.volume_metadata_update(
            self.ctxt,
            1,
            image_metadata2,
            False,
            meta_type=common.METADATA_TYPES.image)
        self.assertEqual(expected2, db_meta)

        # update volume with invalid metadata type.
        self.assertRaises(exception.InvalidMetadataType,
                          db.volume_metadata_update,
                          self.ctxt,
                          1,
                          image_metadata1,
                          False,
                          FAKE_METADATA_TYPE.fake_type)

    @ddt.data(common.METADATA_TYPES.user, common.METADATA_TYPES.image)
    @mock.patch.object(timeutils, 'utcnow')
    @mock.patch.object(sqlalchemy_api, 'resource_exists')
    @mock.patch.object(sqlalchemy_api, 'conditional_update')
    @mock.patch.object(sqlalchemy_api, '_volume_x_metadata_get_query')
    def test_volume_metadata_delete_deleted_at_updated(self,
                                                       meta_type,
                                                       mock_query,
                                                       mock_update,
                                                       mock_resource,
                                                       mock_utc):
        mock_query.all.return_value = {}
        mock_utc.return_value = 'fake_time'

        db.volume_metadata_update(self.ctxt, 1, {}, True, meta_type=meta_type)

        mock_update.assert_called_once_with(mock.ANY, mock.ANY,
                                            {'deleted': True,
                                             'deleted_at': 'fake_time'},
                                            mock.ANY)

    def test_volume_metadata_update_delete(self):
        metadata1 = {'a': '1', 'c': '2'}
        metadata2 = {'a': '3', 'd': '4'}
        should_be = metadata2

        db.volume_create(self.ctxt, {'id': 1, 'metadata': metadata1})
        db_meta = db.volume_metadata_update(self.ctxt, 1, metadata2, True)

        self.assertEqual(should_be, db_meta)

    def test_volume_metadata_delete(self):
        metadata = {'a': 'b', 'c': 'd'}
        db.volume_create(self.ctxt, {'id': 1, 'metadata': metadata})
        db.volume_metadata_delete(self.ctxt, 1, 'c')
        metadata.pop('c')
        self.assertEqual(metadata, db.volume_metadata_get(self.ctxt, 1))

    def test_volume_metadata_delete_with_metatype(self):
        user_metadata = {'a': '1', 'c': '2'}
        image_metadata = {'e': '1', 'f': '2'}
        FAKE_METADATA_TYPE = enum.Enum('METADATA_TYPES', 'fake_type')

        # test that user metadata deleted with meta_type specified.
        db.volume_create(self.ctxt, {'id': 1, 'metadata': user_metadata})
        db.volume_metadata_delete(self.ctxt, 1, 'c',
                                  meta_type=common.METADATA_TYPES.user)
        user_metadata.pop('c')
        self.assertEqual(user_metadata, db.volume_metadata_get(self.ctxt, 1))

        # update the image metadata associated with the volume.
        db.volume_metadata_update(
            self.ctxt,
            1,
            image_metadata,
            False,
            meta_type=common.METADATA_TYPES.image)

        # test that image metadata deleted with meta_type specified.
        db.volume_metadata_delete(self.ctxt, 1, 'e',
                                  meta_type=common.METADATA_TYPES.image)
        image_metadata.pop('e')

        # parse the result to build the dict.
        rows = db.volume_glance_metadata_get(self.ctxt, 1)
        result = {}
        for row in rows:
            result[row['key']] = row['value']
        self.assertEqual(image_metadata, result)

        # delete volume with invalid metadata type.
        self.assertRaises(exception.InvalidMetadataType,
                          db.volume_metadata_delete,
                          self.ctxt,
                          1,
                          'f',
                          FAKE_METADATA_TYPE.fake_type)

    def test_volume_glance_metadata_create(self):
        volume = db.volume_create(self.ctxt, {'host': 'h1'})
        db.volume_glance_metadata_create(self.ctxt, volume['id'],
                                         'image_name',
                                         u'\xe4\xbd\xa0\xe5\xa5\xbd')
        glance_meta = db.volume_glance_metadata_get(self.ctxt, volume['id'])
        for meta_entry in glance_meta:
            if meta_entry.key == 'image_name':
                image_name = meta_entry.value
        self.assertEqual(u'\xe4\xbd\xa0\xe5\xa5\xbd', image_name)

    def test_volume_glance_metadata_list_get(self):
        """Test volume_glance_metadata_list_get in DB API."""
        db.volume_create(self.ctxt, {'id': 'fake1', 'status': 'available',
                                     'host': 'test', 'provider_location': '',
                                     'size': 1})
        db.volume_glance_metadata_create(self.ctxt, 'fake1', 'key1', 'value1')
        db.volume_glance_metadata_create(self.ctxt, 'fake1', 'key2', 'value2')

        db.volume_create(self.ctxt, {'id': 'fake2', 'status': 'available',
                                     'host': 'test', 'provider_location': '',
                                     'size': 1})
        db.volume_glance_metadata_create(self.ctxt, 'fake2', 'key3', 'value3')
        db.volume_glance_metadata_create(self.ctxt, 'fake2', 'key4', 'value4')

        expect_result = [{'volume_id': 'fake1', 'key': 'key1',
                          'value': 'value1'},
                         {'volume_id': 'fake1', 'key': 'key2',
                          'value': 'value2'},
                         {'volume_id': 'fake2', 'key': 'key3',
                          'value': 'value3'},
                         {'volume_id': 'fake2', 'key': 'key4',
                          'value': 'value4'}]
        self._assertEqualListsOfObjects(expect_result,
                                        db.volume_glance_metadata_list_get(
                                            self.ctxt, ['fake1', 'fake2']),
                                        ignored_keys=['id',
                                                      'snapshot_id',
                                                      'created_at',
                                                      'deleted', 'deleted_at',
                                                      'updated_at'])

    def _create_volume_with_image_metadata(self):
        vol1 = db.volume_create(self.ctxt, {'display_name': 'test1'})
        db.volume_glance_metadata_create(self.ctxt, vol1.id, 'image_name',
                                         'imageTestOne')
        db.volume_glance_metadata_create(self.ctxt, vol1.id, 'test_image_key',
                                         'test_image_value')
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2'})
        db.volume_glance_metadata_create(self.ctxt, vol2.id, 'image_name',
                                         'imageTestTwo')
        db.volume_glance_metadata_create(self.ctxt, vol2.id, 'disk_format',
                                         'qcow2')
        return [vol1, vol2]

    def test_volume_get_all_by_image_name_and_key(self):
        vols = self._create_volume_with_image_metadata()
        filters = {'glance_metadata': {'image_name': 'imageTestOne',
                                       'test_image_key': 'test_image_value'}}
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['desc'], filters=filters)
        self._assertEqualListsOfObjects([vols[0]], volumes)

    def test_volume_get_all_by_image_name_and_disk_format(self):
        vols = self._create_volume_with_image_metadata()
        filters = {'glance_metadata': {'image_name': 'imageTestTwo',
                                       'disk_format': 'qcow2'}}
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['desc'], filters=filters)
        self._assertEqualListsOfObjects([vols[1]], volumes)

    def test_volume_get_all_by_invalid_image_metadata(self):
        # Test with invalid image metadata
        self._create_volume_with_image_metadata()
        filters = {'glance_metadata': {'invalid_key': 'invalid_value',
                                       'test_image_key': 'test_image_value'}}
        volumes = db.volume_get_all(self.ctxt, None, None, ['created_at'],
                                    ['desc'], filters=filters)
        self._assertEqualListsOfObjects([], volumes)

    def _create_volumes_to_test_include_in(self):
        """Helper method for test_volume_include_in_* tests."""
        return [
            db.volume_create(self.ctxt,
                             {'host': 'host1@backend1#pool1',
                              'cluster_name': 'cluster1@backend1#pool1'}),
            db.volume_create(self.ctxt,
                             {'host': 'host1@backend2#pool2',
                              'cluster_name': 'cluster1@backend2#pool2'}),
            db.volume_create(self.ctxt,
                             {'host': 'host2@backend#poo1',
                              'cluster_name': 'cluster2@backend#pool'}),
        ]

    @ddt.data('host1@backend1#pool1', 'host1@backend1')
    def test_volume_include_in_cluster_by_host(self, host):
        """Basic volume include test filtering by host and with full rename."""
        vol = self._create_volumes_to_test_include_in()[0]

        cluster_name = 'my_cluster'
        result = db.volume_include_in_cluster(self.ctxt, cluster_name,
                                              partial_rename=False,
                                              host=host)
        self.assertEqual(1, result)
        db_vol = db.volume_get(self.ctxt, vol.id)
        self.assertEqual(cluster_name, db_vol.cluster_name)

    def test_volume_include_in_cluster_by_host_multiple(self):
        """Partial cluster rename filtering with host level info."""
        vols = self._create_volumes_to_test_include_in()[0:2]

        host = 'host1'
        cluster_name = 'my_cluster'
        result = db.volume_include_in_cluster(self.ctxt, cluster_name,
                                              partial_rename=True,
                                              host=host)
        self.assertEqual(2, result)
        db_vols = [db.volume_get(self.ctxt, vols[0].id),
                   db.volume_get(self.ctxt, vols[1].id)]
        for i in range(2):
            self.assertEqual(cluster_name + vols[i].host[len(host):],
                             db_vols[i].cluster_name)

    @ddt.data('cluster1@backend1#pool1', 'cluster1@backend1')
    def test_volume_include_in_cluster_by_cluster_name(self, cluster_name):
        """Basic volume include test filtering by cluster with full rename."""
        vol = self._create_volumes_to_test_include_in()[0]

        new_cluster_name = 'cluster_new@backend1#pool'
        result = db.volume_include_in_cluster(self.ctxt, new_cluster_name,
                                              partial_rename=False,
                                              cluster_name=cluster_name)
        self.assertEqual(1, result)
        db_vol = db.volume_get(self.ctxt, vol.id)
        self.assertEqual(new_cluster_name, db_vol.cluster_name)

    def test_volume_include_in_cluster_by_cluster_multiple(self):
        """Partial rename filtering with cluster with host level info."""
        vols = self._create_volumes_to_test_include_in()[0:2]

        cluster_name = 'cluster1'
        new_cluster_name = 'my_cluster'
        result = db.volume_include_in_cluster(self.ctxt, new_cluster_name,
                                              partial_rename=True,
                                              cluster_name=cluster_name)
        self.assertEqual(2, result)
        db_vols = [db.volume_get(self.ctxt, vols[0].id),
                   db.volume_get(self.ctxt, vols[1].id)]
        for i in range(2):
            self.assertEqual(
                new_cluster_name + vols[i].cluster_name[len(cluster_name):],
                db_vols[i].cluster_name)


@ddt.ddt
class DBAPISnapshotTestCase(BaseTest):

    """Tests for cinder.db.api.snapshot_*."""

    def test_snapshot_data_get_for_project(self):
        actual = db.snapshot_data_get_for_project(self.ctxt, 'project1')
        self.assertEqual((0, 0), actual)
        db.volume_create(self.ctxt, {'id': 1,
                                     'project_id': 'project1',
                                     'size': 42})
        db.snapshot_create(self.ctxt, {'id': 1, 'volume_id': 1,
                                       'project_id': 'project1',
                                       'volume_size': 42})
        actual = db.snapshot_data_get_for_project(self.ctxt, 'project1')
        self.assertEqual((1, 42), actual)

    @ddt.data({'time_collection': [1, 2, 3],
               'latest': 1},
              {'time_collection': [4, 2, 6],
               'latest': 2},
              {'time_collection': [8, 2, 1],
               'latest': 1})
    @ddt.unpack
    def test_snapshot_get_latest_for_volume(self, time_collection, latest):
        def hours_ago(hour):
            return timeutils.utcnow() - datetime.timedelta(
                hours=hour)
        db.volume_create(self.ctxt, {'id': 1})
        for snapshot in time_collection:
            db.snapshot_create(self.ctxt,
                               {'id': snapshot, 'volume_id': 1,
                                'display_name': 'one',
                                'created_at': hours_ago(snapshot),
                                'status': fields.SnapshotStatus.AVAILABLE})

        snapshot = db.snapshot_get_latest_for_volume(self.ctxt, 1)

        self.assertEqual(six.text_type(latest), snapshot['id'])

    def test_snapshot_get_latest_for_volume_not_found(self):

        db.volume_create(self.ctxt, {'id': 1})
        for t_id in [2, 3]:
            db.snapshot_create(self.ctxt,
                               {'id': t_id, 'volume_id': t_id,
                                'display_name': 'one',
                                'status': fields.SnapshotStatus.AVAILABLE})

        self.assertRaises(exception.VolumeSnapshotNotFound,
                          db.snapshot_get_latest_for_volume, self.ctxt, 1)

    def test_snapshot_get_all_by_filter(self):
        db.volume_create(self.ctxt, {'id': 1})
        db.volume_create(self.ctxt, {'id': 2})
        snapshot1 = db.snapshot_create(self.ctxt,
                                       {'id': 1, 'volume_id': 1,
                                        'display_name': 'one',
                                        'status':
                                            fields.SnapshotStatus.AVAILABLE})
        snapshot2 = db.snapshot_create(self.ctxt,
                                       {'id': 2, 'volume_id': 1,
                                        'display_name': 'two',
                                        'status':
                                            fields.SnapshotStatus.CREATING})
        snapshot3 = db.snapshot_create(self.ctxt,
                                       {'id': 3, 'volume_id': 2,
                                        'display_name': 'three',
                                        'status':
                                            fields.SnapshotStatus.AVAILABLE})
        # no filter
        filters = {}
        snapshots = db.snapshot_get_all(self.ctxt, filters=filters)
        self.assertEqual(3, len(snapshots))
        # single match
        filters = {'display_name': 'two'}
        self._assertEqualListsOfObjects([snapshot2],
                                        db.snapshot_get_all(
                                            self.ctxt,
                                            filters),
                                        ignored_keys=['metadata', 'volume'])
        filters = {'volume_id': 2}
        self._assertEqualListsOfObjects([snapshot3],
                                        db.snapshot_get_all(
                                            self.ctxt,
                                            filters),
                                        ignored_keys=['metadata', 'volume'])
        # filter no match
        filters = {'volume_id': 5}
        self._assertEqualListsOfObjects([],
                                        db.snapshot_get_all(
                                            self.ctxt,
                                            filters),
                                        ignored_keys=['metadata', 'volume'])
        filters = {'status': fields.SnapshotStatus.ERROR}
        self._assertEqualListsOfObjects([],
                                        db.snapshot_get_all(
                                            self.ctxt,
                                            filters),
                                        ignored_keys=['metadata', 'volume'])
        # multiple match
        filters = {'volume_id': 1}
        self._assertEqualListsOfObjects([snapshot1, snapshot2],
                                        db.snapshot_get_all(
                                            self.ctxt,
                                            filters),
                                        ignored_keys=['metadata', 'volume'])
        filters = {'status': fields.SnapshotStatus.AVAILABLE}
        self._assertEqualListsOfObjects([snapshot1, snapshot3],
                                        db.snapshot_get_all(
                                            self.ctxt,
                                            filters),
                                        ignored_keys=['metadata', 'volume'])
        filters = {'volume_id': 1, 'status': fields.SnapshotStatus.AVAILABLE}
        self._assertEqualListsOfObjects([snapshot1],
                                        db.snapshot_get_all(
                                            self.ctxt,
                                            filters),
                                        ignored_keys=['metadata', 'volume'])
        filters = {'fake_key': 'fake'}
        self._assertEqualListsOfObjects([],
                                        db.snapshot_get_all(
                                            self.ctxt,
                                            filters),
                                        ignored_keys=['metadata', 'volume'])

    @ddt.data('cluster_name', 'host')
    def test_snapshot_get_all_filter_host_and_cluster(self, field):
        volumes = []
        snapshots = []
        for i in range(2):
            for value in ('host%d@backend#pool', 'host%d@backend', 'host%d'):
                kwargs = {field: value % i}
                vol = utils.create_volume(self.ctxt, **kwargs)
                volumes.append(vol)
                snapshots.append(utils.create_snapshot(self.ctxt, vol.id))

        for i in range(3):
            filters = {field: getattr(volumes[i], field)}
            result = db.snapshot_get_all(self.ctxt, filters=filters)
            self.assertEqual(i + 1, len(result))
            self.assertSetEqual({s.id for s in snapshots[:i + 1]},
                                {s.id for s in result})

    def test_snapshot_get_all_by_host(self):
        db.volume_create(self.ctxt, {'id': 1, 'host': 'host1'})
        db.volume_create(self.ctxt, {'id': 2, 'host': 'host2'})
        snapshot1 = db.snapshot_create(self.ctxt, {'id': 1, 'volume_id': 1})
        snapshot2 = db.snapshot_create(self.ctxt,
                                       {'id': 2,
                                        'volume_id': 2,
                                        'status':
                                            fields.SnapshotStatus.ERROR})

        self._assertEqualListsOfObjects([snapshot1],
                                        db.snapshot_get_all_by_host(
                                            self.ctxt,
                                            'host1'),
                                        ignored_keys='volume')
        self._assertEqualListsOfObjects([snapshot2],
                                        db.snapshot_get_all_by_host(
                                            self.ctxt,
                                            'host2'),
                                        ignored_keys='volume')
        self._assertEqualListsOfObjects(
            [], db.snapshot_get_all_by_host(self.ctxt, 'host2', {
                'status': fields.SnapshotStatus.AVAILABLE}),
            ignored_keys='volume')
        self._assertEqualListsOfObjects(
            [snapshot2], db.snapshot_get_all_by_host(self.ctxt, 'host2', {
                'status': fields.SnapshotStatus.ERROR}),
            ignored_keys='volume')
        self._assertEqualListsOfObjects([],
                                        db.snapshot_get_all_by_host(
                                            self.ctxt,
                                            'host2', {'fake_key': 'fake'}),
                                        ignored_keys='volume')
        # If host is None or empty string, empty list should be returned.
        self.assertEqual([], db.snapshot_get_all_by_host(self.ctxt, None))
        self.assertEqual([], db.snapshot_get_all_by_host(self.ctxt, ''))

    def test_snapshot_get_all_by_host_with_pools(self):
        db.volume_create(self.ctxt, {'id': 1, 'host': 'host1#pool1'})
        db.volume_create(self.ctxt, {'id': 2, 'host': 'host1#pool2'})

        snapshot1 = db.snapshot_create(self.ctxt, {'id': 1, 'volume_id': 1})
        snapshot2 = db.snapshot_create(self.ctxt, {'id': 2, 'volume_id': 2})

        self._assertEqualListsOfObjects([snapshot1, snapshot2],
                                        db.snapshot_get_all_by_host(
                                            self.ctxt,
                                            'host1'),
                                        ignored_keys='volume')
        self._assertEqualListsOfObjects([snapshot1],
                                        db.snapshot_get_all_by_host(
                                            self.ctxt,
                                            'host1#pool1'),
                                        ignored_keys='volume')

        self._assertEqualListsOfObjects([],
                                        db.snapshot_get_all_by_host(
                                            self.ctxt,
                                            'host1#pool0'),
                                        ignored_keys='volume')

    def test_snapshot_get_all_by_project(self):
        db.volume_create(self.ctxt, {'id': 1})
        db.volume_create(self.ctxt, {'id': 2})
        snapshot1 = db.snapshot_create(self.ctxt, {'id': 1, 'volume_id': 1,
                                                   'project_id': 'project1'})
        snapshot2 = db.snapshot_create(
            self.ctxt, {'id': 2, 'volume_id': 2, 'status':
                        fields.SnapshotStatus.ERROR, 'project_id': 'project2'})

        self._assertEqualListsOfObjects([snapshot1],
                                        db.snapshot_get_all_by_project(
                                            self.ctxt,
                                            'project1'),
                                        ignored_keys='volume')
        self._assertEqualListsOfObjects([snapshot2],
                                        db.snapshot_get_all_by_project(
                                            self.ctxt,
                                            'project2'),
                                        ignored_keys='volume')
        self._assertEqualListsOfObjects(
            [], db.snapshot_get_all_by_project(
                self.ctxt,
                'project2',
                {'status': fields.SnapshotStatus.AVAILABLE}),
            ignored_keys='volume')
        self._assertEqualListsOfObjects(
            [snapshot2], db.snapshot_get_all_by_project(
                self.ctxt, 'project2', {
                    'status': fields.SnapshotStatus.ERROR}),
            ignored_keys='volume')
        self._assertEqualListsOfObjects([],
                                        db.snapshot_get_all_by_project(
                                            self.ctxt,
                                            'project2',
                                            {'fake_key': 'fake'}),
                                        ignored_keys='volume')

    def test_snapshot_metadata_get(self):
        metadata = {'a': 'b', 'c': 'd'}
        db.volume_create(self.ctxt, {'id': 1})
        db.snapshot_create(self.ctxt,
                           {'id': 1, 'volume_id': 1, 'metadata': metadata})

        self.assertEqual(metadata, db.snapshot_metadata_get(self.ctxt, 1))

    def test_snapshot_metadata_update(self):
        metadata1 = {'a': '1', 'c': '2'}
        metadata2 = {'a': '3', 'd': '5'}
        should_be = {'a': '3', 'c': '2', 'd': '5'}

        db.volume_create(self.ctxt, {'id': 1})
        db.snapshot_create(self.ctxt,
                           {'id': 1, 'volume_id': 1, 'metadata': metadata1})
        db_meta = db.snapshot_metadata_update(self.ctxt, 1, metadata2, False)

        self.assertEqual(should_be, db_meta)

    def test_snapshot_metadata_update_delete(self):
        metadata1 = {'a': '1', 'c': '2'}
        metadata2 = {'a': '3', 'd': '5'}
        should_be = metadata2

        db.volume_create(self.ctxt, {'id': 1})
        db.snapshot_create(self.ctxt,
                           {'id': 1, 'volume_id': 1, 'metadata': metadata1})
        db_meta = db.snapshot_metadata_update(self.ctxt, 1, metadata2, True)

        self.assertEqual(should_be, db_meta)

    @mock.patch.object(timeutils, 'utcnow')
    @mock.patch.object(sqlalchemy_api, 'resource_exists')
    @mock.patch.object(sqlalchemy_api, '_snapshot_metadata_get')
    @mock.patch.object(sqlalchemy_api, '_snapshot_metadata_get_item')
    def test_snapshot_metadata_delete_deleted_at_updated(self,
                                                         mock_metadata_item,
                                                         mock_metadata,
                                                         mock_resource,
                                                         mock_utc):
        fake_metadata = {'fake_key1': 'fake_value1'}
        mock_item = mock.Mock()
        mock_metadata.return_value = fake_metadata
        mock_utc.return_value = 'fake_time'
        mock_metadata_item.side_effect = [mock_item]

        db.snapshot_metadata_update(self.ctxt, 1, {}, True)

        mock_item.update.assert_called_once_with({'deleted': True,
                                                  'deleted_at': 'fake_time'})

    def test_snapshot_metadata_delete(self):
        metadata = {'a': '1', 'c': '2'}
        should_be = {'a': '1'}

        db.volume_create(self.ctxt, {'id': 1})
        db.snapshot_create(self.ctxt,
                           {'id': 1, 'volume_id': 1, 'metadata': metadata})
        db.snapshot_metadata_delete(self.ctxt, 1, 'c')

        self.assertEqual(should_be, db.snapshot_metadata_get(self.ctxt, 1))


@ddt.ddt
class DBAPIConsistencygroupTestCase(BaseTest):
    def _create_cgs_to_test_include_in(self):
        """Helper method for test_consistencygroup_include_in_* tests."""
        return [
            db.consistencygroup_create(
                self.ctxt, {'host': 'host1@backend1#pool1',
                            'cluster_name': 'cluster1@backend1#pool1'}),
            db.consistencygroup_create(
                self.ctxt, {'host': 'host1@backend2#pool2',
                            'cluster_name': 'cluster1@backend2#pool1'}),
            db.consistencygroup_create(
                self.ctxt, {'host': 'host2@backend#poo1',
                            'cluster_name': 'cluster2@backend#pool'}),
        ]

    @ddt.data('host1@backend1#pool1', 'host1@backend1')
    def test_consistencygroup_include_in_cluster_by_host(self, host):
        """Basic CG include test filtering by host and with full rename."""
        cg = self._create_cgs_to_test_include_in()[0]

        cluster_name = 'my_cluster'
        result = db.consistencygroup_include_in_cluster(self.ctxt,
                                                        cluster_name,
                                                        partial_rename=False,
                                                        host=host)
        self.assertEqual(1, result)
        db_cg = db.consistencygroup_get(self.ctxt, cg.id)
        self.assertEqual(cluster_name, db_cg.cluster_name)

    def test_consistencygroup_include_in_cluster_by_host_multiple(self):
        """Partial cluster rename filtering with host level info."""
        cgs = self._create_cgs_to_test_include_in()[0:2]

        host = 'host1'
        cluster_name = 'my_cluster'
        result = db.consistencygroup_include_in_cluster(self.ctxt,
                                                        cluster_name,
                                                        partial_rename=True,
                                                        host=host)
        self.assertEqual(2, result)
        db_cgs = [db.consistencygroup_get(self.ctxt, cgs[0].id),
                  db.consistencygroup_get(self.ctxt, cgs[1].id)]
        for i in range(2):
            self.assertEqual(cluster_name + cgs[i].host[len(host):],
                             db_cgs[i].cluster_name)

    @ddt.data('cluster1@backend1#pool1', 'cluster1@backend1')
    def test_consistencygroup_include_in_cluster_by_cluster_name(self,
                                                                 cluster_name):
        """Basic CG include test filtering by cluster with full rename."""
        cg = self._create_cgs_to_test_include_in()[0]

        new_cluster_name = 'cluster_new@backend1#pool'
        result = db.consistencygroup_include_in_cluster(
            self.ctxt, new_cluster_name, partial_rename=False,
            cluster_name=cluster_name)

        self.assertEqual(1, result)
        db_cg = db.consistencygroup_get(self.ctxt, cg.id)
        self.assertEqual(new_cluster_name, db_cg.cluster_name)

    def test_consistencygroup_include_in_cluster_by_cluster_multiple(self):
        """Partial rename filtering with cluster with host level info."""
        cgs = self._create_cgs_to_test_include_in()[0:2]

        cluster_name = 'cluster1'
        new_cluster_name = 'my_cluster'
        result = db.consistencygroup_include_in_cluster(
            self.ctxt, new_cluster_name, partial_rename=True,
            cluster_name=cluster_name)

        self.assertEqual(2, result)
        db_cgs = [db.consistencygroup_get(self.ctxt, cgs[0].id),
                  db.consistencygroup_get(self.ctxt, cgs[1].id)]
        for i in range(2):
            self.assertEqual(
                new_cluster_name + cgs[i].cluster_name[len(cluster_name):],
                db_cgs[i].cluster_name)


class DBAPICgsnapshotTestCase(BaseTest):
    """Tests for cinder.db.api.cgsnapshot_*."""

    def _cgsnapshot_create(self, values):
        return utils.create_cgsnapshot(self.ctxt, return_vo=False, **values)

    def test_cgsnapshot_get_all_by_filter(self):
        cgsnapshot1 = self._cgsnapshot_create(
            {'id': fake.CGSNAPSHOT_ID,
             'consistencygroup_id': fake.CONSISTENCY_GROUP_ID})
        cgsnapshot2 = self._cgsnapshot_create(
            {'id': fake.CGSNAPSHOT2_ID,
             'consistencygroup_id': fake.CONSISTENCY_GROUP_ID})
        cgsnapshot3 = self._cgsnapshot_create(
            {'id': fake.CGSNAPSHOT3_ID,
             'consistencygroup_id': fake.CONSISTENCY_GROUP2_ID})
        tests = [
            ({'consistencygroup_id': fake.CONSISTENCY_GROUP_ID},
             [cgsnapshot1, cgsnapshot2]),
            ({'id': fake.CGSNAPSHOT3_ID}, [cgsnapshot3]),
            ({'fake_key': 'fake'}, [])
        ]

        # no filter
        filters = None
        cgsnapshots = db.cgsnapshot_get_all(self.ctxt, filters=filters)
        self.assertEqual(3, len(cgsnapshots))

        for filters, expected in tests:
            self._assertEqualListsOfObjects(expected,
                                            db.cgsnapshot_get_all(
                                                self.ctxt,
                                                filters))

    def test_cgsnapshot_get_all_by_group(self):
        cgsnapshot1 = self._cgsnapshot_create(
            {'id': fake.CGSNAPSHOT_ID,
             'consistencygroup_id': fake.CONSISTENCY_GROUP_ID})
        cgsnapshot2 = self._cgsnapshot_create(
            {'id': fake.CGSNAPSHOT2_ID,
             'consistencygroup_id': fake.CONSISTENCY_GROUP_ID})
        self._cgsnapshot_create(
            {'id': fake.CGSNAPSHOT3_ID,
             'consistencygroup_id': fake.CONSISTENCY_GROUP2_ID})
        tests = [
            ({'consistencygroup_id': fake.CONSISTENCY_GROUP_ID},
             [cgsnapshot1, cgsnapshot2]),
            ({'id': fake.CGSNAPSHOT3_ID}, []),
            ({'consistencygroup_id': fake.CONSISTENCY_GROUP2_ID}, []),
            (None, [cgsnapshot1, cgsnapshot2]),
        ]

        for filters, expected in tests:
            self._assertEqualListsOfObjects(expected,
                                            db.cgsnapshot_get_all_by_group(
                                                self.ctxt,
                                                fake.CONSISTENCY_GROUP_ID,
                                                filters))

        db.cgsnapshot_destroy(self.ctxt, '1')
        db.cgsnapshot_destroy(self.ctxt, '2')
        db.cgsnapshot_destroy(self.ctxt, '3')

    def test_cgsnapshot_get_all_by_project(self):
        cgsnapshot1 = self._cgsnapshot_create(
            {'id': fake.CGSNAPSHOT_ID,
             'consistencygroup_id': fake.CONSISTENCY_GROUP_ID,
             'project_id': fake.PROJECT_ID})
        cgsnapshot2 = self._cgsnapshot_create(
            {'id': fake.CGSNAPSHOT2_ID,
             'consistencygroup_id': fake.CONSISTENCY_GROUP_ID,
             'project_id': fake.PROJECT_ID})
        tests = [
            ({'id': fake.CGSNAPSHOT_ID}, [cgsnapshot1]),
            ({'consistencygroup_id': fake.CONSISTENCY_GROUP_ID},
             [cgsnapshot1, cgsnapshot2]),
            ({'fake_key': 'fake'}, [])
        ]

        for filters, expected in tests:
            self._assertEqualListsOfObjects(expected,
                                            db.cgsnapshot_get_all_by_project(
                                                self.ctxt,
                                                fake.PROJECT_ID,
                                                filters))


class DBAPIVolumeTypeTestCase(BaseTest):

    """Tests for the db.api.volume_type_* methods."""

    def setUp(self):
        self.ctxt = context.get_admin_context()
        super(DBAPIVolumeTypeTestCase, self).setUp()

    def test_volume_type_create_exists(self):
        vt = db.volume_type_create(self.ctxt, {'name': 'n1'})
        self.assertRaises(exception.VolumeTypeExists,
                          db.volume_type_create,
                          self.ctxt,
                          {'name': 'n1'})
        self.assertRaises(exception.VolumeTypeExists,
                          db.volume_type_create,
                          self.ctxt,
                          {'name': 'n2', 'id': vt['id']})

    def test_volume_type_access_remove(self):
        vt = db.volume_type_create(self.ctxt, {'name': 'n1'})
        db.volume_type_access_add(self.ctxt, vt['id'], 'fake_project')
        vtas = db.volume_type_access_get_all(self.ctxt, vt['id'])
        self.assertEqual(1, len(vtas))
        db.volume_type_access_remove(self.ctxt, vt['id'], 'fake_project')
        vtas = db.volume_type_access_get_all(self.ctxt, vt['id'])
        self.assertEqual(0, len(vtas))

    def test_volume_type_access_remove_high_id(self):
        vt = db.volume_type_create(self.ctxt, {'name': 'n1'})
        vta = db.volume_type_access_add(self.ctxt, vt['id'], 'fake_project')
        vtas = db.volume_type_access_get_all(self.ctxt, vt['id'])
        self.assertEqual(1, len(vtas))

        # NOTE(dulek): Bug 1496747 uncovered problems when deleting accesses
        # with id column higher than 128. This is regression test for that
        # case.

        session = sqlalchemy_api.get_session()
        vta.id = 150
        vta.save(session=session)
        session.close()

        db.volume_type_access_remove(self.ctxt, vt['id'], 'fake_project')
        vtas = db.volume_type_access_get_all(self.ctxt, vt['id'])
        self.assertEqual(0, len(vtas))

    def test_get_volume_type_extra_specs(self):
        # Ensure that volume type extra specs can be accessed after
        # the DB session is closed.
        vt_extra_specs = {'mock_key': 'mock_value'}
        vt = db.volume_type_create(self.ctxt,
                                   {'name': 'n1',
                                    'extra_specs': vt_extra_specs})
        volume_ref = db.volume_create(self.ctxt, {'volume_type_id': vt.id})

        session = sqlalchemy_api.get_session()
        volume = sqlalchemy_api._volume_get(self.ctxt, volume_ref.id,
                                            session=session)
        session.close()

        actual_specs = {}
        for spec in volume.volume_type.extra_specs:
            actual_specs[spec.key] = spec.value
        self.assertEqual(vt_extra_specs, actual_specs)


class DBAPIEncryptionTestCase(BaseTest):

    """Tests for the db.api.volume_(type_)?encryption_* methods."""

    _ignored_keys = [
        'deleted',
        'deleted_at',
        'created_at',
        'updated_at',
        'encryption_id',
    ]

    def setUp(self):
        super(DBAPIEncryptionTestCase, self).setUp()
        self.created = \
            [db.volume_type_encryption_create(self.ctxt,
                                              values['volume_type_id'], values)
             for values in self._get_values()]

    def _get_values(self, one=False, updated=False):
        base_values = {
            'cipher': 'fake_cipher',
            'key_size': 256,
            'provider': 'fake_provider',
            'volume_type_id': 'fake_type',
            'control_location': 'front-end',
        }
        updated_values = {
            'cipher': 'fake_updated_cipher',
            'key_size': 512,
            'provider': 'fake_updated_provider',
            'volume_type_id': 'fake_type',
            'control_location': 'front-end',
        }

        if one:
            return base_values

        if updated:
            values = updated_values
        else:
            values = base_values

        def compose(val, step):
            if isinstance(val, str):
                step = str(step)
            return val + step

        return [{k: compose(v, i) for k, v in values.items()}
                for i in range(1, 4)]

    def test_volume_type_encryption_create(self):
        values = self._get_values()
        for i, encryption in enumerate(self.created):
            self._assertEqualObjects(values[i], encryption, self._ignored_keys)

    def test_volume_type_encryption_update(self):
        for values in self._get_values(updated=True):
            db.volume_type_encryption_update(self.ctxt,
                                             values['volume_type_id'], values)
            db_enc = db.volume_type_encryption_get(self.ctxt,
                                                   values['volume_type_id'])
            self._assertEqualObjects(values, db_enc, self._ignored_keys)

    def test_volume_type_encryption_get(self):
        for encryption in self.created:
            encryption_get = \
                db.volume_type_encryption_get(self.ctxt,
                                              encryption['volume_type_id'])
            self._assertEqualObjects(encryption, encryption_get,
                                     self._ignored_keys)

    def test_volume_type_encryption_update_with_no_create(self):
        self.assertRaises(exception.VolumeTypeEncryptionNotFound,
                          db.volume_type_encryption_update,
                          self.ctxt,
                          'fake_no_create_type',
                          {'cipher': 'fake_updated_cipher'})

    def test_volume_type_encryption_delete(self):
        values = {
            'cipher': 'fake_cipher',
            'key_size': 256,
            'provider': 'fake_provider',
            'volume_type_id': 'fake_type',
            'control_location': 'front-end',
        }

        encryption = db.volume_type_encryption_create(self.ctxt, 'fake_type',
                                                      values)
        self._assertEqualObjects(values, encryption, self._ignored_keys)

        db.volume_type_encryption_delete(self.ctxt,
                                         encryption['volume_type_id'])
        encryption_get = \
            db.volume_type_encryption_get(self.ctxt,
                                          encryption['volume_type_id'])
        self.assertIsNone(encryption_get)

    def test_volume_type_encryption_delete_no_create(self):
        self.assertRaises(exception.VolumeTypeEncryptionNotFound,
                          db.volume_type_encryption_delete,
                          self.ctxt,
                          'fake_no_create_type')

    def test_volume_encryption_get(self):
        # normal volume -- metadata should be None
        volume = db.volume_create(self.ctxt, {})
        values = db.volume_encryption_metadata_get(self.ctxt, volume.id)

        self.assertEqual({'encryption_key_id': None}, values)

        # encrypted volume -- metadata should match volume type
        volume_type = self.created[0]

        volume = db.volume_create(self.ctxt, {'volume_type_id':
                                              volume_type['volume_type_id']})
        values = db.volume_encryption_metadata_get(self.ctxt, volume.id)

        expected = {
            'encryption_key_id': volume.encryption_key_id,
            'control_location': volume_type['control_location'],
            'cipher': volume_type['cipher'],
            'key_size': volume_type['key_size'],
            'provider': volume_type['provider'],
        }
        self.assertEqual(expected, values)


class DBAPIReservationTestCase(BaseTest):

    """Tests for db.api.reservation_* methods."""

    def setUp(self):
        super(DBAPIReservationTestCase, self).setUp()
        self.values = {
            'uuid': 'sample-uuid',
            'project_id': 'project1',
            'resource': 'resource',
            'delta': 42,
            'expire': (datetime.datetime.utcnow() +
                       datetime.timedelta(days=1)),
            'usage': {'id': 1}
        }

    def test_reservation_commit(self):
        reservations = _quota_reserve(self.ctxt, 'project1')
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 1, 'in_use': 0},
                    'gigabytes': {'reserved': 2, 'in_use': 0},
                    }
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(
                             self.ctxt, 'project1'))
        db.reservation_commit(self.ctxt, reservations, 'project1')
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 0, 'in_use': 1},
                    'gigabytes': {'reserved': 0, 'in_use': 2},
                    }
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(
                             self.ctxt,
                             'project1'))

    def test_reservation_rollback(self):
        reservations = _quota_reserve(self.ctxt, 'project1')
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 1, 'in_use': 0},
                    'gigabytes': {'reserved': 2, 'in_use': 0},
                    }
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(
                             self.ctxt,
                             'project1'))
        db.reservation_rollback(self.ctxt, reservations, 'project1')
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 0, 'in_use': 0},
                    'gigabytes': {'reserved': 0, 'in_use': 0},
                    }
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(
                             self.ctxt,
                             'project1'))

    def test_reservation_expire(self):
        self.values['expire'] = datetime.datetime.utcnow() + \
            datetime.timedelta(days=1)
        _quota_reserve(self.ctxt, 'project1')
        db.reservation_expire(self.ctxt)

        expected = {'project_id': 'project1',
                    'gigabytes': {'reserved': 0, 'in_use': 0},
                    'volumes': {'reserved': 0, 'in_use': 0}}
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(
                             self.ctxt,
                             'project1'))


class DBAPIMessageTestCase(BaseTest):

    """Tests for message operations"""
    def setUp(self):
        super(DBAPIMessageTestCase, self).setUp()
        self.context = context.get_admin_context()

    def _create_fake_messages(self, m_id, time):
        db.message_create(self.context,
                          {'id': m_id,
                           'event_id': m_id,
                           'message_level': 'error',
                           'project_id': 'fake_id',
                           'expires_at': time})

    def test_cleanup_expired_messages(self):
        now = timeutils.utcnow()
        # message expired 1 day ago
        self._create_fake_messages(
            uuidutils.generate_uuid(), now - datetime.timedelta(days=1))
        # message expired now
        self._create_fake_messages(
            uuidutils.generate_uuid(), now)
        # message expired 1 day after
        self._create_fake_messages(
            uuidutils.generate_uuid(), now + datetime.timedelta(days=1))

        with mock.patch.object(timeutils, 'utcnow') as mock_time_now:
            mock_time_now.return_value = now
            db.cleanup_expired_messages(self.context)
            messages = db.message_get_all(self.context)
            self.assertEqual(2, len(messages))


class DBAPIQuotaClassTestCase(BaseTest):

    """Tests for db.api.quota_class_* methods."""

    def setUp(self):
        super(DBAPIQuotaClassTestCase, self).setUp()
        self.sample_qc = db.quota_class_create(self.ctxt, 'test_qc',
                                               'test_resource', 42)

    def test_quota_class_get(self):
        qc = db.quota_class_get(self.ctxt, 'test_qc', 'test_resource')
        self._assertEqualObjects(self.sample_qc, qc)

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=UTC_NOW)
    def test_quota_class_destroy(self, utcnow_mock):
        self.assertDictEqual(
            {'deleted': True, 'deleted_at': UTC_NOW},
            db.quota_class_destroy(self.ctxt, 'test_qc', 'test_resource'))
        self.assertRaises(exception.QuotaClassNotFound,
                          db.quota_class_get, self.ctxt,
                          'test_qc', 'test_resource')

    def test_quota_class_get_not_found(self):
        self.assertRaises(exception.QuotaClassNotFound,
                          db.quota_class_get, self.ctxt, 'nonexistent',
                          'nonexistent')

    def test_quota_class_get_all_by_name(self):
        db.quota_class_create(self.ctxt, 'test2', 'res1', 43)
        db.quota_class_create(self.ctxt, 'test2', 'res2', 44)
        self.assertEqual({'class_name': 'test_qc', 'test_resource': 42},
                         db.quota_class_get_all_by_name(self.ctxt, 'test_qc'))
        self.assertEqual({'class_name': 'test2', 'res1': 43, 'res2': 44},
                         db.quota_class_get_all_by_name(self.ctxt, 'test2'))

    def test_quota_class_update(self):
        db.quota_class_update(self.ctxt, 'test_qc', 'test_resource', 43)
        updated = db.quota_class_get(self.ctxt, 'test_qc', 'test_resource')
        self.assertEqual(43, updated['hard_limit'])

    def test_quota_class_update_resource(self):
        old = db.quota_class_get(self.ctxt, 'test_qc', 'test_resource')
        db.quota_class_update_resource(self.ctxt,
                                       'test_resource',
                                       'test_resource1')
        new = db.quota_class_get(self.ctxt, 'test_qc', 'test_resource1')
        self.assertEqual(old.id, new.id)
        self.assertEqual('test_resource1', new.resource)

    def test_quota_class_destroy_all_by_name(self):
        db.quota_class_create(self.ctxt, 'test2', 'res1', 43)
        db.quota_class_create(self.ctxt, 'test2', 'res2', 44)
        db.quota_class_destroy_all_by_name(self.ctxt, 'test2')
        self.assertEqual({'class_name': 'test2'},
                         db.quota_class_get_all_by_name(self.ctxt, 'test2'))


class DBAPIQuotaTestCase(BaseTest):

    """Tests for db.api.reservation_* methods."""

    def test_quota_create(self):
        quota = db.quota_create(self.ctxt, 'project1', 'resource', 99)
        self.assertEqual('resource', quota.resource)
        self.assertEqual(99, quota.hard_limit)
        self.assertEqual('project1', quota.project_id)

    def test_quota_get(self):
        quota = db.quota_create(self.ctxt, 'project1', 'resource', 99)
        quota_db = db.quota_get(self.ctxt, 'project1', 'resource')
        self._assertEqualObjects(quota, quota_db)

    def test_quota_get_all_by_project(self):
        for i in range(3):
            for j in range(3):
                db.quota_create(self.ctxt, 'proj%d' % i, 'res%d' % j, j)
        for i in range(3):
            quotas_db = db.quota_get_all_by_project(self.ctxt, 'proj%d' % i)
            self.assertEqual({'project_id': 'proj%d' % i,
                              'res0': 0,
                              'res1': 1,
                              'res2': 2}, quotas_db)

    def test_quota_update(self):
        db.quota_create(self.ctxt, 'project1', 'resource1', 41)
        db.quota_update(self.ctxt, 'project1', 'resource1', 42)
        quota = db.quota_get(self.ctxt, 'project1', 'resource1')
        self.assertEqual(42, quota.hard_limit)
        self.assertEqual('resource1', quota.resource)
        self.assertEqual('project1', quota.project_id)

    def test_quota_update_resource(self):
        old = db.quota_create(self.ctxt, 'project1', 'resource1', 41)
        db.quota_update_resource(self.ctxt, 'resource1', 'resource2')
        new = db.quota_get(self.ctxt, 'project1', 'resource2')
        self.assertEqual(old.id, new.id)
        self.assertEqual('resource2', new.resource)

    def test_quota_update_nonexistent(self):
        self.assertRaises(exception.ProjectQuotaNotFound,
                          db.quota_update,
                          self.ctxt,
                          'project1',
                          'resource1',
                          42)

    def test_quota_get_nonexistent(self):
        self.assertRaises(exception.ProjectQuotaNotFound,
                          db.quota_get,
                          self.ctxt,
                          'project1',
                          'resource1')

    def test_quota_reserve(self):
        reservations = _quota_reserve(self.ctxt, 'project1')
        self.assertEqual(2, len(reservations))
        quota_usage = db.quota_usage_get_all_by_project(self.ctxt, 'project1')
        self.assertEqual({'project_id': 'project1',
                          'gigabytes': {'reserved': 2, 'in_use': 0},
                          'volumes': {'reserved': 1, 'in_use': 0}},
                         quota_usage)

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=UTC_NOW)
    def test_quota_destroy(self, utcnow_mock):
        db.quota_create(self.ctxt, 'project1', 'resource1', 41)
        self.assertDictEqual(
            {'deleted': True, 'deleted_at': UTC_NOW},
            db.quota_destroy(self.ctxt, 'project1', 'resource1'))
        self.assertRaises(exception.ProjectQuotaNotFound, db.quota_get,
                          self.ctxt, 'project1', 'resource1')

    def test_quota_destroy_by_project(self):
        # Create limits, reservations and usage for project
        project = 'project1'
        _quota_reserve(self.ctxt, project)
        expected_usage = {'project_id': project,
                          'volumes': {'reserved': 1, 'in_use': 0},
                          'gigabytes': {'reserved': 2, 'in_use': 0}}
        expected = {'project_id': project, 'gigabytes': 2, 'volumes': 1}

        # Check that quotas are there
        self.assertEqual(expected,
                         db.quota_get_all_by_project(self.ctxt, project))
        self.assertEqual(expected_usage,
                         db.quota_usage_get_all_by_project(self.ctxt, project))

        # Destroy only the limits
        db.quota_destroy_by_project(self.ctxt, project)

        # Confirm that limits have been removed
        self.assertEqual({'project_id': project},
                         db.quota_get_all_by_project(self.ctxt, project))

        # But that usage and reservations are the same
        self.assertEqual(expected_usage,
                         db.quota_usage_get_all_by_project(self.ctxt, project))

    def test_quota_destroy_sqlalchemy_all_by_project_(self):
        # Create limits, reservations and usage for project
        project = 'project1'
        _quota_reserve(self.ctxt, project)
        expected_usage = {'project_id': project,
                          'volumes': {'reserved': 1, 'in_use': 0},
                          'gigabytes': {'reserved': 2, 'in_use': 0}}
        expected = {'project_id': project, 'gigabytes': 2, 'volumes': 1}
        expected_result = {'project_id': project}

        # Check that quotas are there
        self.assertEqual(expected,
                         db.quota_get_all_by_project(self.ctxt, project))
        self.assertEqual(expected_usage,
                         db.quota_usage_get_all_by_project(self.ctxt, project))

        # Destroy all quotas using SQLAlchemy Implementation
        sqlalchemy_api.quota_destroy_all_by_project(self.ctxt, project,
                                                    only_quotas=False)

        # Check that all quotas have been deleted
        self.assertEqual(expected_result,
                         db.quota_get_all_by_project(self.ctxt, project))
        self.assertEqual(expected_result,
                         db.quota_usage_get_all_by_project(self.ctxt, project))

    def test_quota_usage_get_nonexistent(self):
        self.assertRaises(exception.QuotaUsageNotFound,
                          db.quota_usage_get,
                          self.ctxt,
                          'p1',
                          'nonexitent_resource')

    def test_quota_usage_get(self):
        _quota_reserve(self.ctxt, 'p1')
        quota_usage = db.quota_usage_get(self.ctxt, 'p1', 'gigabytes')
        expected = {'resource': 'gigabytes', 'project_id': 'p1',
                    'in_use': 0, 'reserved': 2, 'total': 2}
        for key, value in expected.items():
            self.assertEqual(value, quota_usage[key], key)

    def test_quota_usage_get_all_by_project(self):
        _quota_reserve(self.ctxt, 'p1')
        expected = {'project_id': 'p1',
                    'volumes': {'in_use': 0, 'reserved': 1},
                    'gigabytes': {'in_use': 0, 'reserved': 2}}
        self.assertEqual(expected, db.quota_usage_get_all_by_project(
                         self.ctxt, 'p1'))


class DBAPIBackupTestCase(BaseTest):

    """Tests for db.api.backup_* methods."""

    _ignored_keys = ['id', 'deleted', 'deleted_at', 'created_at',
                     'updated_at', 'data_timestamp', 'backup_metadata']

    def setUp(self):
        super(DBAPIBackupTestCase, self).setUp()
        self.created = [db.backup_create(self.ctxt, values)
                        for values in self._get_values()]

    def _get_values(self, one=False):
        base_values = {
            'user_id': fake.USER_ID,
            'project_id': fake.PROJECT_ID,
            'volume_id': 'volume',
            'host': 'host',
            'availability_zone': 'zone',
            'display_name': 'display',
            'display_description': 'description',
            'container': 'container',
            'status': 'status',
            'fail_reason': 'test',
            'service_metadata': 'metadata',
            'service': 'service',
            'parent_id': "parent_id",
            'size': 1000,
            'object_count': 100,
            'temp_volume_id': 'temp_volume_id',
            'temp_snapshot_id': 'temp_snapshot_id',
            'num_dependent_backups': 0,
            'snapshot_id': 'snapshot_id',
            'restore_volume_id': 'restore_volume_id'}
        if one:
            return base_values

        def compose(val, step):
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                step = str(step)
            return val + step

        return [{k: compose(v, i) for k, v in base_values.items()}
                for i in range(1, 4)]

    def test_backup_create(self):
        values = self._get_values()
        for i, backup in enumerate(self.created):
            self.assertEqual(36, len(backup['id']))  # dynamic UUID
            self._assertEqualObjects(values[i], backup, self._ignored_keys)

    def test_backup_get(self):
        for backup in self.created:
            backup_get = db.backup_get(self.ctxt, backup['id'])
            self._assertEqualObjects(backup, backup_get)

    def test_backup_get_deleted(self):
        backup_dic = {'user_id': fake.USER_ID,
                      'project_id': fake.PROJECT_ID,
                      'volume_id': fake.VOLUME_ID,
                      'size': 1,
                      'object_count': 1}
        backup = objects.Backup(self.ctxt, **backup_dic)
        backup.create()
        backup.destroy()
        backup_get = db.backup_get(self.ctxt, backup.id, read_deleted='yes')
        self.assertEqual(backup.id, backup_get.id)

    def tests_backup_get_all(self):
        all_backups = db.backup_get_all(self.ctxt)
        self._assertEqualListsOfObjects(self.created, all_backups)

    def tests_backup_get_all_by_filter(self):
        filters = {'status': self.created[1]['status']}
        filtered_backups = db.backup_get_all(self.ctxt, filters=filters)
        self._assertEqualListsOfObjects([self.created[1]], filtered_backups)

        filters = {'display_name': self.created[1]['display_name']}
        filtered_backups = db.backup_get_all(self.ctxt, filters=filters)
        self._assertEqualListsOfObjects([self.created[1]], filtered_backups)

        filters = {'volume_id': self.created[1]['volume_id']}
        filtered_backups = db.backup_get_all(self.ctxt, filters=filters)
        self._assertEqualListsOfObjects([self.created[1]], filtered_backups)

        filters = {'fake_key': 'fake'}
        filtered_backups = db.backup_get_all(self.ctxt, filters=filters)
        self._assertEqualListsOfObjects([], filtered_backups)

    def test_backup_get_all_by_host(self):
        byhost = db.backup_get_all_by_host(self.ctxt,
                                           self.created[1]['host'])
        self._assertEqualObjects(self.created[1], byhost[0])

    def test_backup_get_all_by_project(self):
        byproj = db.backup_get_all_by_project(self.ctxt,
                                              self.created[1]['project_id'])
        self._assertEqualObjects(self.created[1], byproj[0])

        byproj = db.backup_get_all_by_project(self.ctxt,
                                              self.created[1]['project_id'],
                                              {'fake_key': 'fake'})
        self._assertEqualListsOfObjects([], byproj)

    def test_backup_get_all_by_volume(self):
        byvol = db.backup_get_all_by_volume(self.ctxt,
                                            self.created[1]['volume_id'])
        self._assertEqualObjects(self.created[1], byvol[0])

        byvol = db.backup_get_all_by_volume(self.ctxt,
                                            self.created[1]['volume_id'],
                                            {'fake_key': 'fake'})
        self._assertEqualListsOfObjects([], byvol)

    def test_backup_update_nonexistent(self):
        self.assertRaises(exception.BackupNotFound,
                          db.backup_update,
                          self.ctxt, 'nonexistent', {})

    def test_backup_update(self):
        updated_values = self._get_values(one=True)
        update_id = self.created[1]['id']
        db.backup_update(self.ctxt, update_id, updated_values)
        updated_backup = db.backup_get(self.ctxt, update_id)
        self._assertEqualObjects(updated_values, updated_backup,
                                 self._ignored_keys)

    def test_backup_update_with_fail_reason_truncation(self):
        updated_values = self._get_values(one=True)
        fail_reason = '0' * 512
        updated_values['fail_reason'] = fail_reason

        update_id = self.created[1]['id']
        db.backup_update(self.ctxt, update_id, updated_values)
        updated_backup = db.backup_get(self.ctxt, update_id)
        updated_values['fail_reason'] = fail_reason[:255]
        self._assertEqualObjects(updated_values, updated_backup,
                                 self._ignored_keys)

    @mock.patch('oslo_utils.timeutils.utcnow', return_value=UTC_NOW)
    def test_backup_destroy(self, utcnow_mock):
        for backup in self.created:
            self.assertDictEqual(
                {'status': fields.BackupStatus.DELETED, 'deleted': True,
                 'deleted_at': UTC_NOW},
                db.backup_destroy(self.ctxt, backup['id']))
        self.assertFalse(db.backup_get_all(self.ctxt))

    def test_backup_not_found(self):
        self.assertRaises(exception.BackupNotFound, db.backup_get, self.ctxt,
                          'notinbase')


class DBAPIProcessSortParamTestCase(test.TestCase):

    def test_process_sort_params_defaults(self):
        """Verifies default sort parameters."""
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params([], [])
        self.assertEqual(['created_at', 'id'], sort_keys)
        self.assertEqual(['asc', 'asc'], sort_dirs)

        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(None, None)
        self.assertEqual(['created_at', 'id'], sort_keys)
        self.assertEqual(['asc', 'asc'], sort_dirs)

    def test_process_sort_params_override_default_keys(self):
        """Verifies that the default keys can be overridden."""
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            [], [], default_keys=['key1', 'key2', 'key3'])
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        self.assertEqual(['asc', 'asc', 'asc'], sort_dirs)

    def test_process_sort_params_override_default_dir(self):
        """Verifies that the default direction can be overridden."""
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            [], [], default_dir='dir1')
        self.assertEqual(['created_at', 'id'], sort_keys)
        self.assertEqual(['dir1', 'dir1'], sort_dirs)

    def test_process_sort_params_override_default_key_and_dir(self):
        """Verifies that the default key and dir can be overridden."""
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            [], [], default_keys=['key1', 'key2', 'key3'],
            default_dir='dir1')
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        self.assertEqual(['dir1', 'dir1', 'dir1'], sort_dirs)

        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            [], [], default_keys=[], default_dir='dir1')
        self.assertEqual([], sort_keys)
        self.assertEqual([], sort_dirs)

    def test_process_sort_params_non_default(self):
        """Verifies that non-default keys are added correctly."""
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['key1', 'key2'], ['asc', 'desc'])
        self.assertEqual(['key1', 'key2', 'created_at', 'id'], sort_keys)
        # First sort_dir in list is used when adding the default keys
        self.assertEqual(['asc', 'desc', 'asc', 'asc'], sort_dirs)

    def test_process_sort_params_default(self):
        """Verifies that default keys are added correctly."""
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2'], ['asc', 'desc'])
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['asc', 'desc', 'asc'], sort_dirs)

        # Include default key value, rely on default direction
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2'], [])
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['asc', 'asc', 'asc'], sort_dirs)

    def test_process_sort_params_default_dir(self):
        """Verifies that the default dir is applied to all keys."""
        # Direction is set, ignore default dir
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2'], ['desc'], default_dir='dir')
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'desc', 'desc'], sort_dirs)

        # But should be used if no direction is set
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2'], [], default_dir='dir')
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['dir', 'dir', 'dir'], sort_dirs)

    def test_process_sort_params_unequal_length(self):
        """Verifies that a sort direction list is applied correctly."""
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2', 'key3'], ['desc'])
        self.assertEqual(['id', 'key2', 'key3', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'desc', 'desc', 'desc'], sort_dirs)

        # Default direction is the first key in the list
        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2', 'key3'], ['desc', 'asc'])
        self.assertEqual(['id', 'key2', 'key3', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'asc', 'desc', 'desc'], sort_dirs)

        sort_keys, sort_dirs = sqlalchemy_api.process_sort_params(
            ['id', 'key2', 'key3'], ['desc', 'asc', 'asc'])
        self.assertEqual(['id', 'key2', 'key3', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'asc', 'asc', 'desc'], sort_dirs)

    def test_process_sort_params_extra_dirs_lengths(self):
        """InvalidInput raised if more directions are given."""
        self.assertRaises(exception.InvalidInput,
                          sqlalchemy_api.process_sort_params,
                          ['key1', 'key2'],
                          ['asc', 'desc', 'desc'])

    def test_process_sort_params_invalid_sort_dir(self):
        """InvalidInput raised if invalid directions are given."""
        for dirs in [['foo'], ['asc', 'foo'], ['asc', 'desc', 'foo']]:
            self.assertRaises(exception.InvalidInput,
                              sqlalchemy_api.process_sort_params,
                              ['key'],
                              dirs)


class DBAPIDriverInitiatorDataTestCase(BaseTest):
    initiator = 'iqn.1993-08.org.debian:01:222'
    namespace = 'test_ns'

    def _test_insert(self, key, value, expected_result=True):
        result = db.driver_initiator_data_insert_by_key(
            self.ctxt, self.initiator, self.namespace, key, value)
        self.assertEqual(expected_result, result)

        data = db.driver_initiator_data_get(self.ctxt, self.initiator,
                                            self.namespace)
        self.assertEqual(data[0].key, key)
        self.assertEqual(data[0].value, value)

    def test_insert(self):
        self._test_insert('key1', 'foo')

    def test_insert_already_exists(self):
        self._test_insert('key2', 'bar')
        self._test_insert('key2', 'bar', expected_result=False)


@ddt.ddt
class DBAPIImageVolumeCacheEntryTestCase(BaseTest):

    def _validate_entry(self, entry, host, cluster_name, image_id,
                        image_updated_at, volume_id, size):
        self.assertIsNotNone(entry)
        self.assertIsNotNone(entry['id'])
        self.assertEqual(host, entry['host'])
        self.assertEqual(cluster_name, entry['cluster_name'])
        self.assertEqual(image_id, entry['image_id'])
        self.assertEqual(image_updated_at, entry['image_updated_at'])
        self.assertEqual(volume_id, entry['volume_id'])
        self.assertEqual(size, entry['size'])
        self.assertIsNotNone(entry['last_used'])

    def test_create_delete_query_cache_entry(self):
        host = 'abc@123#poolz'
        cluster_name = 'def@123#poolz'
        image_id = 'c06764d7-54b0-4471-acce-62e79452a38b'
        image_updated_at = datetime.datetime.utcnow()
        volume_id = 'e0e4f819-24bb-49e6-af1e-67fb77fc07d1'
        size = 6

        entry = db.image_volume_cache_create(self.ctxt, host, cluster_name,
                                             image_id, image_updated_at,
                                             volume_id, size)
        self._validate_entry(entry, host, cluster_name, image_id,
                             image_updated_at, volume_id, size)

        entry = db.image_volume_cache_get_and_update_last_used(self.ctxt,
                                                               image_id,
                                                               host=host)
        self._validate_entry(entry, host, cluster_name, image_id,
                             image_updated_at, volume_id, size)

        entry = db.image_volume_cache_get_by_volume_id(self.ctxt, volume_id)
        self._validate_entry(entry, host, cluster_name, image_id,
                             image_updated_at, volume_id, size)

        db.image_volume_cache_delete(self.ctxt, entry['volume_id'])

        entry = db.image_volume_cache_get_and_update_last_used(self.ctxt,
                                                               image_id,
                                                               host=host)
        self.assertIsNone(entry)

    def test_cache_entry_get_multiple(self):
        host = 'abc@123#poolz'
        cluster_name = 'def@123#poolz'
        image_id = 'c06764d7-54b0-4471-acce-62e79452a38b'
        image_updated_at = datetime.datetime.utcnow()
        volume_id = 'e0e4f819-24bb-49e6-af1e-67fb77fc07d1'
        size = 6

        entries = []
        for i in range(0, 3):
            entries.append(db.image_volume_cache_create(self.ctxt,
                                                        host,
                                                        cluster_name,
                                                        image_id,
                                                        image_updated_at,
                                                        volume_id,
                                                        size))
        # It is considered OK for the cache to have multiple of the same
        # entries. Expect only a single one from the query.
        entry = db.image_volume_cache_get_and_update_last_used(self.ctxt,
                                                               image_id,
                                                               host=host)
        self._validate_entry(entry, host, cluster_name, image_id,
                             image_updated_at, volume_id, size)

        # We expect to get the same one on subsequent queries due to the
        # last_used field being updated each time and ordering by it.
        entry_id = entry['id']
        entry = db.image_volume_cache_get_and_update_last_used(self.ctxt,
                                                               image_id,
                                                               host=host)
        self._validate_entry(entry, host, cluster_name, image_id,
                             image_updated_at, volume_id, size)
        self.assertEqual(entry_id, entry['id'])

        # Cleanup
        for entry in entries:
            db.image_volume_cache_delete(self.ctxt, entry['volume_id'])

    def test_cache_entry_get_none(self):
        host = 'abc@123#poolz'
        image_id = 'c06764d7-54b0-4471-acce-62e79452a38b'
        entry = db.image_volume_cache_get_and_update_last_used(self.ctxt,
                                                               image_id,
                                                               host=host)
        self.assertIsNone(entry)

    def test_cache_entry_get_by_volume_id_none(self):
        volume_id = 'e0e4f819-24bb-49e6-af1e-67fb77fc07d1'
        entry = db.image_volume_cache_get_by_volume_id(self.ctxt, volume_id)
        self.assertIsNone(entry)

    def test_cache_entry_get_all_for_host(self):
        host = 'abc@123#poolz'
        image_updated_at = datetime.datetime.utcnow()
        size = 6

        entries = []
        for i in range(0, 3):
            entries.append(db.image_volume_cache_create(self.ctxt,
                                                        host,
                                                        'cluster-%s' % i,
                                                        'image-' + str(i),
                                                        image_updated_at,
                                                        'vol-' + str(i),
                                                        size))

        other_entry = db.image_volume_cache_create(self.ctxt,
                                                   'someOtherHost',
                                                   'someOtherCluster',
                                                   'image-12345',
                                                   image_updated_at,
                                                   'vol-1234',
                                                   size)

        found_entries = db.image_volume_cache_get_all(self.ctxt, host=host)
        self.assertIsNotNone(found_entries)
        self.assertEqual(len(entries), len(found_entries))
        for found_entry in found_entries:
            for entry in entries:
                if found_entry['id'] == entry['id']:
                    self._validate_entry(found_entry,
                                         entry['host'],
                                         entry['cluster_name'],
                                         entry['image_id'],
                                         entry['image_updated_at'],
                                         entry['volume_id'],
                                         entry['size'])

        # Cleanup
        db.image_volume_cache_delete(self.ctxt, other_entry['volume_id'])
        for entry in entries:
            db.image_volume_cache_delete(self.ctxt, entry['volume_id'])

    def test_cache_entry_get_all_for_host_none(self):
        host = 'abc@123#poolz'
        entries = db.image_volume_cache_get_all(self.ctxt, host=host)
        self.assertEqual([], entries)

    @ddt.data('host1@backend1#pool1', 'host1@backend1')
    def test_cache_entry_include_in_cluster_by_host(self, host):
        """Basic cache include test filtering by host and with full rename."""
        image_updated_at = datetime.datetime.utcnow()
        image_cache = (
            db.image_volume_cache_create(
                self.ctxt, 'host1@backend1#pool1', 'cluster1@backend1#pool1',
                'image-1', image_updated_at, 'vol-1', 6),
            db.image_volume_cache_create(
                self.ctxt, 'host1@backend2#pool2', 'cluster1@backend2#pool2',
                'image-2', image_updated_at, 'vol-2', 6),
            db.image_volume_cache_create(
                self.ctxt, 'host2@backend#pool', 'cluster2@backend#pool',
                'image-3', image_updated_at, 'vol-3', 6),

        )

        cluster_name = 'my_cluster'
        result = db.image_volume_cache_include_in_cluster(self.ctxt,
                                                          cluster_name,
                                                          partial_rename=False,
                                                          host=host)
        self.assertEqual(1, result)
        db_image_cache = db.image_volume_cache_get_by_volume_id(
            self.ctxt, image_cache[0].volume_id)
        self.assertEqual(cluster_name, db_image_cache.cluster_name)


class DBAPIGenericTestCase(BaseTest):
    def test_resource_exists_volume(self):
        # NOTE(geguileo): We create 2 volumes in this test (even if the second
        # one is not being used) to confirm that the DB exists subquery is
        # properly formulated and doesn't result in multiple rows, as such
        # case would raise an exception when converting the result to an
        # scalar.  This would happen if for example the query wasn't generated
        # directly using get_session but using model_query like this:
        #  query = model_query(context, model,
        #                      sql.exists().where(and_(*conditions)))
        # Instead of what we do:
        #  query = get_session().query(sql.exists().where(and_(*conditions)))
        db.volume_create(self.ctxt, {'id': fake.VOLUME_ID})
        db.volume_create(self.ctxt, {'id': fake.VOLUME2_ID})
        model = db.get_model_for_versioned_object(objects.Volume)
        res = sqlalchemy_api.resource_exists(self.ctxt, model, fake.VOLUME_ID)
        self.assertTrue(res, msg="Couldn't find existing Volume")

    def test_resource_exists_volume_fails(self):
        db.volume_create(self.ctxt, {'id': fake.VOLUME_ID})
        model = db.get_model_for_versioned_object(objects.Volume)
        res = sqlalchemy_api.resource_exists(self.ctxt, model, fake.VOLUME2_ID)
        self.assertFalse(res, msg='Found nonexistent Volume')

    def test_resource_exists_snapshot(self):
        # Read NOTE in test_resource_exists_volume on why we create 2 snapshots
        vol = db.volume_create(self.ctxt, {'id': fake.VOLUME_ID})
        db.snapshot_create(self.ctxt, {'id': fake.SNAPSHOT_ID,
                                       'volume_id': vol.id})
        db.snapshot_create(self.ctxt, {'id': fake.SNAPSHOT2_ID,
                                       'volume_id': vol.id})
        model = db.get_model_for_versioned_object(objects.Snapshot)
        res = sqlalchemy_api.resource_exists(self.ctxt, model,
                                             fake.SNAPSHOT_ID)
        self.assertTrue(res, msg="Couldn't find existing Snapshot")

    def test_resource_exists_snapshot_fails(self):
        vol = db.volume_create(self.ctxt, {'id': fake.VOLUME_ID})
        db.snapshot_create(self.ctxt, {'id': fake.SNAPSHOT_ID,
                                       'volume_id': vol.id})
        model = db.get_model_for_versioned_object(objects.Snapshot)
        res = sqlalchemy_api.resource_exists(self.ctxt, model,
                                             fake.SNAPSHOT2_ID)
        self.assertFalse(res, msg='Found nonexistent Snapshot')

    def test_resource_exists_volume_project_separation(self):
        user_context = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                              is_admin=False)
        user2_context = context.RequestContext(fake.USER2_ID, fake.PROJECT2_ID,
                                               is_admin=False)
        volume = db.volume_create(user_context,
                                  {'project_id': fake.PROJECT_ID})
        model = db.get_model_for_versioned_object(objects.Volume)

        # Owner can find it
        res = sqlalchemy_api.resource_exists(user_context, model, volume.id)
        self.assertTrue(res, msg='Owner cannot find its own Volume')

        # Non admin user that is not the owner cannot find it
        res = sqlalchemy_api.resource_exists(user2_context, model, volume.id)
        self.assertFalse(res, msg="Non admin user can find somebody else's "
                                  "volume")

        # Admin can find it
        res = sqlalchemy_api.resource_exists(self.ctxt, model, volume.id)
        self.assertTrue(res, msg="Admin cannot find the volume")

    def test_resource_exists_snapshot_project_separation(self):
        user_context = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                              is_admin=False)
        user2_context = context.RequestContext(fake.USER2_ID, fake.PROJECT2_ID,
                                               is_admin=False)
        vol = db.volume_create(user_context, {'project_id': fake.PROJECT_ID})
        snap = db.snapshot_create(self.ctxt, {'project_id': fake.PROJECT_ID,
                                              'volume_id': vol.id})
        model = db.get_model_for_versioned_object(objects.Snapshot)

        # Owner can find it
        res = sqlalchemy_api.resource_exists(user_context, model, snap.id)
        self.assertTrue(res, msg='Owner cannot find its own Snapshot')

        # Non admin user that is not the owner cannot find it
        res = sqlalchemy_api.resource_exists(user2_context, model, snap.id)
        self.assertFalse(res, msg="Non admin user can find somebody else's "
                                  "Snapshot")

        # Admin can find it
        res = sqlalchemy_api.resource_exists(self.ctxt, model, snap.id)
        self.assertTrue(res, msg="Admin cannot find the Snapshot")


@ddt.ddt
class DBAPIBackendTestCase(BaseTest):
    @ddt.data((True, True), (True, False), (False, True), (False, False))
    @ddt.unpack
    def test_is_backend_frozen_service(self, frozen, pool):
        service = utils.create_service(self.ctxt, {'frozen': frozen})
        utils.create_service(self.ctxt, {'host': service.host + '2',
                                         'frozen': not frozen})
        host = service.host
        if pool:
            host += '#poolname'
        self.assertEqual(frozen, db.is_backend_frozen(self.ctxt, host,
                                                      service.cluster_name))

    @ddt.data((True, True), (True, False), (False, True), (False, False))
    @ddt.unpack
    def test_is_backend_frozen_cluster(self, frozen, pool):
        cluster = utils.create_cluster(self.ctxt, frozen=frozen)
        utils.create_service(self.ctxt, {'frozen': frozen, 'host': 'hostA',
                                         'cluster_name': cluster.name})
        service = utils.create_service(self.ctxt,
                                       {'frozen': not frozen,
                                        'host': 'hostB',
                                        'cluster_name': cluster.name})
        utils.create_populated_cluster(self.ctxt, 3, 0, frozen=not frozen,
                                       name=cluster.name + '2')
        host = service.host
        cluster = service.cluster_name
        if pool:
            host += '#poolname'
            cluster += '#poolname'
        self.assertEqual(frozen,
                         db.is_backend_frozen(self.ctxt, host, cluster))


@ddt.ddt
class DBAPIGroupTestCase(BaseTest):
    def test_group_get_all_by_host(self):
        grp_type = db.group_type_create(self.ctxt, {'name': 'my_group_type'})
        groups = []
        backend = 'host1@lvm'
        for i in range(3):
            groups.append([db.group_create(
                self.ctxt,
                {'host': '%(b)s%(n)d' % {'b': backend, 'n': i},
                 'group_type_id': grp_type['id']})
                for j in range(3)])

        for i in range(3):
            host = '%(b)s%(n)d' % {'b': backend, 'n': i}
            filters = {'host': host, 'backend_match_level': 'backend'}
            grps = db.group_get_all(
                self.ctxt, filters=filters)
            self._assertEqualListsOfObjects(groups[i], grps)
            for grp in grps:
                db.group_destroy(self.ctxt, grp['id'])

        db.group_type_destroy(self.ctxt, grp_type['id'])

    def test_group_get_all_by_host_with_pools(self):
        grp_type = db.group_type_create(self.ctxt, {'name': 'my_group_type'})
        groups = []
        backend = 'host1@lvm'
        pool = '%s#pool1' % backend
        grp_on_host_wo_pool = [db.group_create(
            self.ctxt,
            {'host': backend,
             'group_type_id': grp_type['id']})
            for j in range(3)]
        grp_on_host_w_pool = [db.group_create(
            self.ctxt,
            {'host': pool,
             'group_type_id': grp_type['id']})]
        groups.append(grp_on_host_wo_pool + grp_on_host_w_pool)
        # insert an additional record that doesn't belongs to the same
        # host as 'foo' and test if it is included in the result
        grp_foobar = db.group_create(self.ctxt,
                                     {'host': '%sfoo' % backend,
                                      'group_type_id': grp_type['id']})

        filters = {'host': backend, 'backend_match_level': 'backend'}
        grps = db.group_get_all(self.ctxt, filters=filters)
        self._assertEqualListsOfObjects(groups[0], grps)
        for grp in grps:
            db.group_destroy(self.ctxt, grp['id'])

        db.group_destroy(self.ctxt, grp_foobar['id'])

        db.group_type_destroy(self.ctxt, grp_type['id'])

    def _create_gs_to_test_include_in(self):
        """Helper method for test_group_include_in_* tests."""
        return [
            db.group_create(
                self.ctxt, {'host': 'host1@backend1#pool1',
                            'cluster_name': 'cluster1@backend1#pool1'}),
            db.group_create(
                self.ctxt, {'host': 'host1@backend2#pool2',
                            'cluster_name': 'cluster1@backend2#pool1'}),
            db.group_create(
                self.ctxt, {'host': 'host2@backend#poo1',
                            'cluster_name': 'cluster2@backend#pool'}),
        ]

    @ddt.data('host1@backend1#pool1', 'host1@backend1')
    def test_group_include_in_cluster_by_host(self, host):
        group = self._create_gs_to_test_include_in()[0]

        cluster_name = 'my_cluster'
        result = db.group_include_in_cluster(self.ctxt, cluster_name,
                                             partial_rename=False, host=host)
        self.assertEqual(1, result)
        db_group = db.group_get(self.ctxt, group.id)
        self.assertEqual(cluster_name, db_group.cluster_name)

    def test_group_include_in_cluster_by_host_multiple(self):
        groups = self._create_gs_to_test_include_in()[0:2]

        host = 'host1'
        cluster_name = 'my_cluster'
        result = db.group_include_in_cluster(self.ctxt, cluster_name,
                                             partial_rename=True, host=host)
        self.assertEqual(2, result)
        db_group = [db.group_get(self.ctxt, groups[0].id),
                    db.group_get(self.ctxt, groups[1].id)]
        for i in range(2):
            self.assertEqual(cluster_name + groups[i].host[len(host):],
                             db_group[i].cluster_name)

    @ddt.data('cluster1@backend1#pool1', 'cluster1@backend1')
    def test_group_include_in_cluster_by_cluster_name(self, cluster_name):
        group = self._create_gs_to_test_include_in()[0]

        new_cluster_name = 'cluster_new@backend1#pool'
        result = db.group_include_in_cluster(self.ctxt, new_cluster_name,
                                             partial_rename=False,
                                             cluster_name=cluster_name)

        self.assertEqual(1, result)
        db_group = db.group_get(self.ctxt, group.id)
        self.assertEqual(new_cluster_name, db_group.cluster_name)

    def test_group_include_in_cluster_by_cluster_multiple(self):
        groups = self._create_gs_to_test_include_in()[0:2]

        cluster_name = 'cluster1'
        new_cluster_name = 'my_cluster'
        result = db.group_include_in_cluster(self.ctxt, new_cluster_name,
                                             partial_rename=True,
                                             cluster_name=cluster_name)

        self.assertEqual(2, result)
        db_groups = [db.group_get(self.ctxt, groups[0].id),
                     db.group_get(self.ctxt, groups[1].id)]
        for i in range(2):
            self.assertEqual(
                new_cluster_name + groups[i].cluster_name[len(cluster_name):],
                db_groups[i].cluster_name)
