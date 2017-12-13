
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import datetime

import mock
from oslo_config import cfg
from oslo_config import fixture as config_fixture
from oslo_utils import timeutils
import six

from cinder import backup
from cinder.backup import api as backup_api
from cinder import context
from cinder import db
from cinder.db.sqlalchemy import api as sqa_api
from cinder.db.sqlalchemy import models as sqa_models
from cinder import exception
from cinder import objects
from cinder.objects import fields
from cinder import quota
from cinder import quota_utils
from cinder import test
from cinder.tests.unit import fake_constants as fake
import cinder.tests.unit.image.fake
from cinder.tests.unit import utils as tests_utils
from cinder import volume


CONF = cfg.CONF


class QuotaIntegrationTestCase(test.TestCase):

    def setUp(self):
        objects.register_all()
        super(QuotaIntegrationTestCase, self).setUp()
        self.volume_type_name = CONF.default_volume_type
        self.volume_type = objects.VolumeType(context.get_admin_context(),
                                              name=self.volume_type_name,
                                              description='',
                                              is_public=False,
                                              projects=[],
                                              extra_specs={})
        self.volume_type.create()

        self.addCleanup(db.volume_type_destroy, context.get_admin_context(),
                        self.volume_type['id'])

        self.flags(quota_volumes=2,
                   quota_snapshots=2,
                   quota_gigabytes=20,
                   quota_backups=2,
                   quota_backup_gigabytes=20)

        self.user_id = fake.USER_ID
        self.project_id = fake.PROJECT_ID
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              is_admin=True)

        # Destroy the 'default' quota_class in the database to avoid
        # conflicts with the test cases here that are setting up their own
        # defaults.
        db.quota_class_destroy_all_by_name(self.context, 'default')
        self.addCleanup(cinder.tests.unit.image.fake.FakeImageService_reset)

    def _create_volume(self, size=1):
        """Create a test volume."""
        vol = {}
        vol['user_id'] = self.user_id
        vol['project_id'] = self.project_id
        vol['size'] = size
        vol['status'] = 'available'
        vol['volume_type_id'] = self.volume_type['id']
        vol['host'] = 'fake_host'
        vol['availability_zone'] = 'fake_zone'
        vol['attach_status'] = fields.VolumeAttachStatus.DETACHED
        volume = objects.Volume(context=self.context, **vol)
        volume.create()
        return volume

    def _create_snapshot(self, volume):
        snapshot = objects.Snapshot(self.context)
        snapshot.user_id = self.user_id or fake.USER_ID
        snapshot.project_id = self.project_id or fake.PROJECT_ID
        snapshot.volume_id = volume['id']
        snapshot.volume_size = volume['size']
        snapshot.status = fields.SnapshotStatus.AVAILABLE
        snapshot.create()
        return snapshot

    def _create_backup(self, volume):
        backup = {}
        backup['user_id'] = self.user_id
        backup['project_id'] = self.project_id
        backup['volume_id'] = volume['id']
        backup['volume_size'] = volume['size']
        backup['status'] = fields.BackupStatus.AVAILABLE
        return db.backup_create(self.context, backup)

    def test_volume_size_limit_exceeds(self):
        resource = 'volumes_%s' % self.volume_type_name
        db.quota_class_create(self.context, 'default', resource, 1)
        flag_args = {
            'quota_volumes': 10,
            'quota_gigabytes': 1000,
            'per_volume_size_limit': 5
        }
        self.flags(**flag_args)
        self.assertRaises(exception.VolumeSizeExceedsLimit,
                          volume.API().create,
                          self.context, 10, '', '',)

    def test_too_many_volumes(self):
        volume_ids = []
        for _i in range(CONF.quota_volumes):
            vol_ref = self._create_volume()
            volume_ids.append(vol_ref['id'])
        ex = self.assertRaises(exception.VolumeLimitExceeded,
                               volume.API().create,
                               self.context, 1, '', '',
                               volume_type=self.volume_type)
        msg = ("Maximum number of volumes allowed (%d) exceeded for"
               " quota 'volumes'." % CONF.quota_volumes)
        self.assertEqual(msg, six.text_type(ex))
        for volume_id in volume_ids:
            db.volume_destroy(self.context, volume_id)

    def test_too_many_volumes_of_type(self):
        resource = 'volumes_%s' % self.volume_type_name
        db.quota_class_create(self.context, 'default', resource, 1)
        flag_args = {
            'quota_volumes': 2000,
            'quota_gigabytes': 2000
        }
        self.flags(**flag_args)
        vol_ref = self._create_volume()
        ex = self.assertRaises(exception.VolumeLimitExceeded,
                               volume.API().create,
                               self.context, 1, '', '',
                               volume_type=self.volume_type)
        msg = ("Maximum number of volumes allowed (1) exceeded for"
               " quota '%s'." % resource)
        self.assertEqual(msg, six.text_type(ex))
        vol_ref.destroy()

    def test__snapshots_quota_value(self):
        test_volume1 = tests_utils.create_volume(
            self.context,
            status='available',
            host=CONF.host)
        test_volume2 = tests_utils.create_volume(
            self.context,
            status='available',
            host=CONF.host)
        volume_api = cinder.volume.api.API()
        volume_api.create_snapshots_in_db(self.context,
                                          [test_volume1, test_volume2],
                                          'fake_name',
                                          'fake_description',
                                          fake.CONSISTENCY_GROUP_ID)
        usages = db.quota_usage_get_all_by_project(self.context,
                                                   self.project_id)
        self.assertEqual(2, usages['snapshots']['in_use'])

    def test_too_many_snapshots_of_type(self):
        resource = 'snapshots_%s' % self.volume_type_name
        db.quota_class_create(self.context, 'default', resource, 1)
        flag_args = {
            'quota_volumes': 2000,
            'quota_gigabytes': 2000,
        }
        self.flags(**flag_args)
        vol_ref = self._create_volume()
        snap_ref = self._create_snapshot(vol_ref)
        self.assertRaises(exception.SnapshotLimitExceeded,
                          volume.API().create_snapshot,
                          self.context, vol_ref, '', '')
        snap_ref.destroy()
        vol_ref.destroy()

    def test_too_many_backups(self):
        resource = 'backups'
        db.quota_class_create(self.context, 'default', resource, 1)
        flag_args = {
            'quota_backups': 2000,
            'quota_backup_gigabytes': 2000
        }
        self.flags(**flag_args)
        vol_ref = self._create_volume()
        backup_ref = self._create_backup(vol_ref)
        with mock.patch.object(backup_api.API,
                               '_get_available_backup_service_host') as \
                mock__get_available_backup_service:
            mock__get_available_backup_service.return_value = 'host'
            self.assertRaises(exception.BackupLimitExceeded,
                              backup.API().create,
                              self.context,
                              'name',
                              'description',
                              vol_ref['id'],
                              'container',
                              False,
                              None)
            db.backup_destroy(self.context, backup_ref['id'])
            db.volume_destroy(self.context, vol_ref['id'])

    def test_too_many_gigabytes(self):
        volume_ids = []
        vol_ref = self._create_volume(size=20)
        volume_ids.append(vol_ref['id'])
        raised_exc = self.assertRaises(
            exception.VolumeSizeExceedsAvailableQuota, volume.API().create,
            self.context, 1, '', '', volume_type=self.volume_type)
        expected = exception.VolumeSizeExceedsAvailableQuota(
            requested=1, quota=20, consumed=20)
        self.assertEqual(str(expected), str(raised_exc))
        for volume_id in volume_ids:
            db.volume_destroy(self.context, volume_id)

    def test_too_many_combined_gigabytes(self):
        vol_ref = self._create_volume(size=10)
        snap_ref = self._create_snapshot(vol_ref)
        self.assertRaises(exception.QuotaError,
                          volume.API().create_snapshot,
                          self.context, vol_ref, '', '')
        usages = db.quota_usage_get_all_by_project(self.context,
                                                   self.project_id)
        self.assertEqual(20, usages['gigabytes']['in_use'])
        snap_ref.destroy()
        vol_ref.destroy()

    def test_too_many_combined_backup_gigabytes(self):
        vol_ref = self._create_volume(size=10000)
        backup_ref = self._create_backup(vol_ref)
        with mock.patch.object(backup_api.API,
                               '_get_available_backup_service_host') as \
                mock__get_available_backup_service:
            mock__get_available_backup_service.return_value = 'host'
            self.assertRaises(
                exception.VolumeBackupSizeExceedsAvailableQuota,
                backup.API().create,
                context=self.context,
                name='name',
                description='description',
                volume_id=vol_ref['id'],
                container='container',
                incremental=False)
            db.backup_destroy(self.context, backup_ref['id'])
            vol_ref.destroy()

    def test_no_snapshot_gb_quota_flag(self):
        self.flags(quota_volumes=2,
                   quota_snapshots=2,
                   quota_gigabytes=20,
                   no_snapshot_gb_quota=True)
        vol_ref = self._create_volume(size=10)
        snap_ref = self._create_snapshot(vol_ref)
        snap_ref2 = volume.API().create_snapshot(self.context,
                                                 vol_ref, '', '')

        # Make sure the snapshot volume_size isn't included in usage.
        vol_ref2 = volume.API().create(self.context, 10, '', '')
        usages = db.quota_usage_get_all_by_project(self.context,
                                                   self.project_id)
        self.assertEqual(20, usages['gigabytes']['in_use'])
        self.assertEqual(0, usages['gigabytes']['reserved'])

        snap_ref.destroy()
        snap_ref2.destroy()
        vol_ref.destroy()
        vol_ref2.destroy()

    def test_backup_gb_quota_flag(self):
        self.flags(quota_volumes=2,
                   quota_snapshots=2,
                   quota_backups=2,
                   quota_gigabytes=20
                   )
        vol_ref = self._create_volume(size=10)
        backup_ref = self._create_backup(vol_ref)
        with mock.patch.object(backup_api.API,
                               '_get_available_backup_service_host') as \
                mock_mock__get_available_backup_service:
            mock_mock__get_available_backup_service.return_value = 'host'
            backup_ref2 = backup.API().create(self.context,
                                              'name',
                                              'description',
                                              vol_ref['id'],
                                              'container',
                                              False,
                                              None)

            # Make sure the backup volume_size isn't included in usage.
            vol_ref2 = volume.API().create(self.context, 10, '', '')
            usages = db.quota_usage_get_all_by_project(self.context,
                                                       self.project_id)
            self.assertEqual(20, usages['gigabytes']['in_use'])
            self.assertEqual(0, usages['gigabytes']['reserved'])

            db.backup_destroy(self.context, backup_ref['id'])
            db.backup_destroy(self.context, backup_ref2['id'])
            vol_ref.destroy()
            vol_ref2.destroy()

    def test_too_many_gigabytes_of_type(self):
        resource = 'gigabytes_%s' % self.volume_type_name
        db.quota_class_create(self.context, 'default', resource, 10)
        flag_args = {
            'quota_volumes': 2000,
            'quota_gigabytes': 2000,
        }
        self.flags(**flag_args)
        vol_ref = self._create_volume(size=10)
        raised_exc = self.assertRaises(
            exception.VolumeSizeExceedsAvailableQuota, volume.API().create,
            self.context, 1, '', '', volume_type=self.volume_type)
        expected = exception.VolumeSizeExceedsAvailableQuota(
            requested=1, quota=10, consumed=10, name=resource)
        self.assertEqual(str(expected), str(raised_exc))
        vol_ref.destroy()


class FakeContext(object):
    def __init__(self, project_id, quota_class):
        self.is_admin = False
        self.user_id = 'fake_user'
        self.project_id = project_id
        self.quota_class = quota_class

    def elevated(self):
        elevated = self.__class__(self.project_id, self.quota_class)
        elevated.is_admin = True
        return elevated


class FakeDriver(object):
    def __init__(self, by_project=None, by_class=None, reservations=None):
        self.called = []
        self.by_project = by_project or {}
        self.by_class = by_class or {}
        self.reservations = reservations or []

    def get_by_project(self, context, project_id, resource):
        self.called.append(('get_by_project', context, project_id, resource))
        try:
            return self.by_project[project_id][resource]
        except KeyError:
            raise exception.ProjectQuotaNotFound(project_id=project_id)

    def get_by_class(self, context, quota_class, resource):
        self.called.append(('get_by_class', context, quota_class, resource))
        try:
            return self.by_class[quota_class][resource]
        except KeyError:
            raise exception.QuotaClassNotFound(class_name=quota_class)

    def get_default(self, context, resource, parent_project_id=None):
        self.called.append(('get_default', context, resource,
                            parent_project_id))
        return resource.default

    def get_defaults(self, context, resources, parent_project_id=None):
        self.called.append(('get_defaults', context, resources,
                            parent_project_id))
        return resources

    def get_class_quotas(self, context, resources, quota_class,
                         defaults=True):
        self.called.append(('get_class_quotas', context, resources,
                            quota_class, defaults))
        return resources

    def get_project_quotas(self, context, resources, project_id,
                           quota_class=None, defaults=True, usages=True):
        self.called.append(('get_project_quotas', context, resources,
                            project_id, quota_class, defaults, usages))
        return resources

    def limit_check(self, context, resources, values, project_id=None):
        self.called.append(('limit_check', context, resources,
                            values, project_id))

    def reserve(self, context, resources, deltas, expire=None,
                project_id=None):
        self.called.append(('reserve', context, resources, deltas,
                            expire, project_id))
        return self.reservations

    def commit(self, context, reservations, project_id=None):
        self.called.append(('commit', context, reservations, project_id))

    def rollback(self, context, reservations, project_id=None):
        self.called.append(('rollback', context, reservations, project_id))

    def destroy_by_project(self, context, project_id):
        self.called.append(('destroy_by_project', context, project_id))

    def expire(self, context):
        self.called.append(('expire', context))


class BaseResourceTestCase(test.TestCase):
    def test_no_flag(self):
        resource = quota.BaseResource('test_resource')
        self.assertEqual('test_resource', resource.name)
        self.assertIsNone(resource.flag)
        self.assertEqual(-1, resource.default)

    def test_with_flag(self):
        # We know this flag exists, so use it...
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        self.assertEqual('test_resource', resource.name)
        self.assertEqual('quota_volumes', resource.flag)
        self.assertEqual(10, resource.default)

    def test_with_flag_no_quota(self):
        self.flags(quota_volumes=-1)
        resource = quota.BaseResource('test_resource', 'quota_volumes')

        self.assertEqual('test_resource', resource.name)
        self.assertEqual('quota_volumes', resource.flag)
        self.assertEqual(-1, resource.default)

    def test_quota_no_project_no_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver()
        context = FakeContext(None, None)
        quota_value = resource.quota(driver, context)

        self.assertEqual(10, quota_value)

    def test_quota_with_project_no_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver(
            by_project=dict(
                test_project=dict(test_resource=15), ))
        context = FakeContext('test_project', None)
        quota_value = resource.quota(driver, context)

        self.assertEqual(15, quota_value)

    def test_quota_no_project_with_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver(
            by_class=dict(
                test_class=dict(test_resource=20), ))
        context = FakeContext(None, 'test_class')
        quota_value = resource.quota(driver, context)

        self.assertEqual(20, quota_value)

    def test_quota_with_project_with_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver(by_project=dict(
            test_project=dict(test_resource=15), ),
            by_class=dict(test_class=dict(test_resource=20), ))
        context = FakeContext('test_project', 'test_class')
        quota_value = resource.quota(driver, context)

        self.assertEqual(15, quota_value)

    def test_quota_override_project_with_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver(by_project=dict(
            test_project=dict(test_resource=15),
            override_project=dict(test_resource=20), ))
        context = FakeContext('test_project', 'test_class')
        quota_value = resource.quota(driver, context,
                                     project_id='override_project')

        self.assertEqual(20, quota_value)

    def test_quota_override_subproject_no_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes',
                                      parent_project_id='test_parent_project')
        driver = FakeDriver()
        context = FakeContext('test_project', None)
        quota_value = resource.quota(driver, context)

        self.assertEqual(0, quota_value)

    def test_quota_with_project_override_class(self):
        self.flags(quota_volumes=10)
        resource = quota.BaseResource('test_resource', 'quota_volumes')
        driver = FakeDriver(by_class=dict(
            test_class=dict(test_resource=15),
            override_class=dict(test_resource=20), ))
        context = FakeContext('test_project', 'test_class')
        quota_value = resource.quota(driver, context,
                                     quota_class='override_class')

        self.assertEqual(20, quota_value)


class VolumeTypeResourceTestCase(test.TestCase):
    def test_name_and_flag(self):
        volume_type_name = 'foo'
        volume = {'name': volume_type_name, 'id': 'myid'}
        resource = quota.VolumeTypeResource('volumes', volume)

        self.assertEqual('volumes_%s' % volume_type_name, resource.name)
        self.assertIsNone(resource.flag)
        self.assertEqual(-1, resource.default)


class QuotaEngineTestCase(test.TestCase):
    def test_init(self):
        quota_obj = quota.QuotaEngine()

        self.assertEqual({}, quota_obj.resources)
        self.assertIsInstance(quota_obj._driver, quota.DbQuotaDriver)

    def test_init_override_string(self):
        quota_obj = quota.QuotaEngine(
            quota_driver_class='cinder.tests.unit.test_quota.FakeDriver')

        self.assertEqual({}, quota_obj.resources)
        self.assertIsInstance(quota_obj._driver, FakeDriver)

    def test_init_override_obj(self):
        quota_obj = quota.QuotaEngine(quota_driver_class=FakeDriver)

        self.assertEqual({}, quota_obj.resources)
        self.assertEqual(FakeDriver, quota_obj._driver)

    def test_register_resource(self):
        quota_obj = quota.QuotaEngine()
        resource = quota.AbsoluteResource('test_resource')
        quota_obj.register_resource(resource)

        self.assertEqual(dict(test_resource=resource), quota_obj.resources)

    def test_register_resources(self):
        quota_obj = quota.QuotaEngine()
        resources = [
            quota.AbsoluteResource('test_resource1'),
            quota.AbsoluteResource('test_resource2'),
            quota.AbsoluteResource('test_resource3'), ]
        quota_obj.register_resources(resources)

        self.assertEqual(dict(test_resource1=resources[0],
                              test_resource2=resources[1],
                              test_resource3=resources[2], ),
                         quota_obj.resources)

    def test_get_by_project(self):
        context = FakeContext('test_project', 'test_class')
        driver = FakeDriver(
            by_project=dict(
                test_project=dict(test_resource=42)))
        quota_obj = quota.QuotaEngine(quota_driver_class=driver)
        result = quota_obj.get_by_project(context, 'test_project',
                                          'test_resource')

        self.assertEqual([('get_by_project',
                           context,
                           'test_project',
                           'test_resource'), ], driver.called)
        self.assertEqual(42, result)

    def test_get_by_class(self):
        context = FakeContext('test_project', 'test_class')
        driver = FakeDriver(
            by_class=dict(
                test_class=dict(test_resource=42)))
        quota_obj = quota.QuotaEngine(quota_driver_class=driver)
        result = quota_obj.get_by_class(context, 'test_class', 'test_resource')

        self.assertEqual([('get_by_class',
                           context,
                           'test_class',
                           'test_resource'), ], driver.called)
        self.assertEqual(42, result)

    def _make_quota_obj(self, driver):
        quota_obj = quota.QuotaEngine(quota_driver_class=driver)
        resources = [
            quota.AbsoluteResource('test_resource4'),
            quota.AbsoluteResource('test_resource3'),
            quota.AbsoluteResource('test_resource2'),
            quota.AbsoluteResource('test_resource1'), ]
        quota_obj.register_resources(resources)

        return quota_obj

    def test_get_defaults(self):
        context = FakeContext(None, None)
        parent_project_id = None
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        result = quota_obj.get_defaults(context)

        self.assertEqual([('get_defaults',
                          context,
                          quota_obj.resources,
                          parent_project_id), ], driver.called)
        self.assertEqual(quota_obj.resources, result)

    def test_get_class_quotas(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.get_class_quotas(context, 'test_class')
        result2 = quota_obj.get_class_quotas(context, 'test_class', False)

        self.assertEqual([
            ('get_class_quotas',
             context,
             quota_obj.resources,
             'test_class', True),
            ('get_class_quotas',
             context, quota_obj.resources,
             'test_class', False), ], driver.called)
        self.assertEqual(quota_obj.resources, result1)
        self.assertEqual(quota_obj.resources, result2)

    def test_get_project_quotas(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.get_project_quotas(context, 'test_project')
        result2 = quota_obj.get_project_quotas(context, 'test_project',
                                               quota_class='test_class',
                                               defaults=False,
                                               usages=False)

        self.assertEqual([
            ('get_project_quotas',
             context,
             quota_obj.resources,
             'test_project',
             None,
             True,
             True),
            ('get_project_quotas',
             context,
             quota_obj.resources,
             'test_project',
             'test_class',
             False,
             False), ], driver.called)
        self.assertEqual(quota_obj.resources, result1)
        self.assertEqual(quota_obj.resources, result2)

    def test_get_subproject_quotas(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.get_project_quotas(context, 'test_project')
        result2 = quota_obj.get_project_quotas(context, 'test_project',
                                               quota_class='test_class',
                                               defaults=False,
                                               usages=False)

        self.assertEqual([
            ('get_project_quotas',
             context,
             quota_obj.resources,
             'test_project',
             None,
             True,
             True),
            ('get_project_quotas',
             context,
             quota_obj.resources,
             'test_project',
             'test_class',
             False,
             False), ], driver.called)
        self.assertEqual(quota_obj.resources, result1)
        self.assertEqual(quota_obj.resources, result2)

    def test_count_no_resource(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        self.assertRaises(exception.QuotaResourceUnknown,
                          quota_obj.count, context, 'test_resource5',
                          True, foo='bar')

    def test_count_wrong_resource(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        self.assertRaises(exception.QuotaResourceUnknown,
                          quota_obj.count, context, 'test_resource1',
                          True, foo='bar')

    def test_count(self):
        def fake_count(context, *args, **kwargs):
            self.assertEqual((True,), args)
            self.assertEqual(dict(foo='bar'), kwargs)
            return 5

        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.register_resource(quota.CountableResource('test_resource5',
                                                            fake_count))
        result = quota_obj.count(context, 'test_resource5', True, foo='bar')

        self.assertEqual(5, result)

    def test_limit_check(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.limit_check(context, test_resource1=4, test_resource2=3,
                              test_resource3=2, test_resource4=1)

        self.assertEqual([
            ('limit_check',
             context,
             quota_obj.resources,
             dict(
                 test_resource1=4,
                 test_resource2=3,
                 test_resource3=2,
                 test_resource4=1,),
             None), ],
            driver.called)

    def test_reserve(self):
        context = FakeContext(None, None)
        driver = FakeDriver(reservations=['resv-01',
                                          'resv-02',
                                          'resv-03',
                                          'resv-04', ])
        quota_obj = self._make_quota_obj(driver)
        result1 = quota_obj.reserve(context, test_resource1=4,
                                    test_resource2=3, test_resource3=2,
                                    test_resource4=1)
        result2 = quota_obj.reserve(context, expire=3600,
                                    test_resource1=1, test_resource2=2,
                                    test_resource3=3, test_resource4=4)
        result3 = quota_obj.reserve(context, project_id='fake_project',
                                    test_resource1=1, test_resource2=2,
                                    test_resource3=3, test_resource4=4)

        self.assertEqual([
            ('reserve',
             context,
             quota_obj.resources,
             dict(
                 test_resource1=4,
                 test_resource2=3,
                 test_resource3=2,
                 test_resource4=1, ),
             None,
             None),
            ('reserve',
             context,
             quota_obj.resources,
             dict(
                 test_resource1=1,
                 test_resource2=2,
                 test_resource3=3,
                 test_resource4=4, ),
             3600,
             None),
            ('reserve',
             context,
             quota_obj.resources,
             dict(
                 test_resource1=1,
                 test_resource2=2,
                 test_resource3=3,
                 test_resource4=4, ),
             None,
             'fake_project'), ],
            driver.called)
        self.assertEqual(['resv-01',
                          'resv-02',
                          'resv-03',
                          'resv-04', ], result1)
        self.assertEqual(['resv-01',
                          'resv-02',
                          'resv-03',
                          'resv-04', ], result2)
        self.assertEqual(['resv-01',
                          'resv-02',
                          'resv-03',
                          'resv-04', ], result3)

    def test_commit(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.commit(context, ['resv-01', 'resv-02', 'resv-03'])

        self.assertEqual([('commit',
                           context,
                           ['resv-01',
                            'resv-02',
                            'resv-03'],
                           None), ],
                         driver.called)

    def test_rollback(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.rollback(context, ['resv-01', 'resv-02', 'resv-03'])

        self.assertEqual([('rollback',
                           context,
                           ['resv-01',
                            'resv-02',
                            'resv-03'],
                           None), ],
                         driver.called)

    def test_destroy_by_project(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.destroy_by_project(context, 'test_project')

        self.assertEqual([('destroy_by_project',
                           context,
                           'test_project'), ],
                         driver.called)

    def test_expire(self):
        context = FakeContext(None, None)
        driver = FakeDriver()
        quota_obj = self._make_quota_obj(driver)
        quota_obj.expire(context)

        self.assertEqual([('expire', context), ], driver.called)

    def test_resource_names(self):
        quota_obj = self._make_quota_obj(None)

        self.assertEqual(['test_resource1', 'test_resource2',
                          'test_resource3', 'test_resource4'],
                         quota_obj.resource_names)


class VolumeTypeQuotaEngineTestCase(test.TestCase):
    def test_default_resources(self):
        def fake_vtga(context, inactive=False, filters=None):
            return {}
        self.mock_object(db, 'volume_type_get_all', fake_vtga)

        engine = quota.VolumeTypeQuotaEngine()
        self.assertEqual(['backup_gigabytes', 'backups',
                          'gigabytes', 'per_volume_gigabytes',
                          'snapshots', 'volumes'],
                         engine.resource_names)

    def test_volume_type_resources(self):
        ctx = context.RequestContext('admin', 'admin', is_admin=True)
        vtype = db.volume_type_create(ctx, {'name': 'type1'})
        vtype2 = db.volume_type_create(ctx, {'name': 'type_2'})

        def fake_vtga(context, inactive=False, filters=None):
            return {
                'type1': {
                    'id': vtype['id'],
                    'name': 'type1',
                    'extra_specs': {},
                },
                'type_2': {
                    'id': vtype['id'],
                    'name': 'type_2',
                    'extra_specs': {},
                },
            }
        self.mock_object(db, 'volume_type_get_all', fake_vtga)

        engine = quota.VolumeTypeQuotaEngine()
        self.assertEqual(['backup_gigabytes', 'backups',
                          'gigabytes', 'gigabytes_type1', 'gigabytes_type_2',
                          'per_volume_gigabytes', 'snapshots',
                          'snapshots_type1', 'snapshots_type_2', 'volumes',
                          'volumes_type1', 'volumes_type_2',
                          ], engine.resource_names)
        db.volume_type_destroy(ctx, vtype['id'])
        db.volume_type_destroy(ctx, vtype2['id'])

    def test_update_quota_resource(self):
        ctx = context.RequestContext('admin', 'admin', is_admin=True)

        engine = quota.VolumeTypeQuotaEngine()
        engine.update_quota_resource(ctx, 'type1', 'type2')


class DbQuotaDriverBaseTestCase(test.TestCase):
    def setUp(self):
        super(DbQuotaDriverBaseTestCase, self).setUp()

        self.flags(quota_volumes=10,
                   quota_snapshots=10,
                   quota_gigabytes=1000,
                   quota_backups=10,
                   quota_backup_gigabytes=1000,
                   reservation_expire=86400,
                   until_refresh=0,
                   max_age=0,
                   )

        # These can be used for expected defaults for child/non-child
        self._default_quotas_non_child = dict(
            volumes=10,
            snapshots=10,
            gigabytes=1000,
            backups=10,
            backup_gigabytes=1000,
            per_volume_gigabytes=-1)
        self._default_quotas_child = dict(
            volumes=0,
            snapshots=0,
            gigabytes=0,
            backups=0,
            backup_gigabytes=0,
            per_volume_gigabytes=0)

        self.calls = []

        patcher = mock.patch.object(timeutils, 'utcnow')
        self.addCleanup(patcher.stop)
        self.mock_utcnow = patcher.start()
        self.mock_utcnow.return_value = datetime.datetime.utcnow()

    def _mock_quota_class_get_default(self):
        # Mock quota_class_get_default
        def fake_qcgd(context):
            self.calls.append('quota_class_get_defaults')
            return dict(volumes=10,
                        snapshots=10,
                        gigabytes=1000,
                        backups=10,
                        backup_gigabytes=1000
                        )
        self.mock_object(db, 'quota_class_get_defaults', fake_qcgd)

    def _mock_volume_type_get_all(self):
        def fake_vtga(context, inactive=False, filters=None):
            return {}
        self.mock_object(db, 'volume_type_get_all', fake_vtga)

    def _mock_quota_class_get_all_by_name(self):
        # Mock quota_class_get_all_by_name
        def fake_qcgabn(context, quota_class):
            self.calls.append('quota_class_get_all_by_name')
            self.assertEqual('test_class', quota_class)
            return dict(gigabytes=500, volumes=10, snapshots=10, backups=10,
                        backup_gigabytes=500)
        self.mock_object(db, 'quota_class_get_all_by_name', fake_qcgabn)

    def _mock_allocated_get_all_by_project(self, allocated_quota=False):
        def fake_qagabp(context, project_id, session=None):
            self.calls.append('quota_allocated_get_all_by_project')
            if allocated_quota:
                return dict(project_id=project_id, volumes=3)
            return dict(project_id=project_id)

        self.mock_object(db, 'quota_allocated_get_all_by_project', fake_qagabp)


class DbQuotaDriverTestCase(DbQuotaDriverBaseTestCase):
    def setUp(self):
        super(DbQuotaDriverTestCase, self).setUp()

        self.driver = quota.DbQuotaDriver()

    def test_get_defaults(self):
        # Use our pre-defined resources
        self._mock_quota_class_get_default()
        self._mock_volume_type_get_all()
        result = self.driver.get_defaults(None, quota.QUOTAS.resources)

        self.assertEqual(
            dict(
                volumes=10,
                snapshots=10,
                gigabytes=1000,
                backups=10,
                backup_gigabytes=1000,
                per_volume_gigabytes=-1), result)

    def test_get_class_quotas(self):
        self._mock_quota_class_get_all_by_name()
        self._mock_volume_type_get_all()
        result = self.driver.get_class_quotas(None, quota.QUOTAS.resources,
                                              'test_class')

        self.assertEqual(['quota_class_get_all_by_name'], self.calls)
        self.assertEqual(dict(volumes=10,
                         gigabytes=500,
                         snapshots=10,
                         backups=10,
                         backup_gigabytes=500,
                         per_volume_gigabytes=-1), result)

    def test_get_class_quotas_no_defaults(self):
        self._mock_quota_class_get_all_by_name()
        result = self.driver.get_class_quotas(None, quota.QUOTAS.resources,
                                              'test_class', False)

        self.assertEqual(['quota_class_get_all_by_name'], self.calls)
        self.assertEqual(dict(volumes=10,
                              gigabytes=500,
                              snapshots=10,
                              backups=10,
                              backup_gigabytes=500), result)

    def _mock_get_by_project(self):
        def fake_qgabp(context, project_id):
            self.calls.append('quota_get_all_by_project')
            self.assertEqual('test_project', project_id)
            return dict(volumes=10, gigabytes=50, reserved=0,
                        snapshots=10, backups=10,
                        backup_gigabytes=50)

        def fake_qugabp(context, project_id):
            self.calls.append('quota_usage_get_all_by_project')
            self.assertEqual('test_project', project_id)
            return dict(volumes=dict(in_use=2, reserved=0),
                        snapshots=dict(in_use=2, reserved=0),
                        gigabytes=dict(in_use=10, reserved=0),
                        backups=dict(in_use=2, reserved=0),
                        backup_gigabytes=dict(in_use=10, reserved=0)
                        )

        self.mock_object(db, 'quota_get_all_by_project', fake_qgabp)
        self.mock_object(db, 'quota_usage_get_all_by_project', fake_qugabp)

        self._mock_quota_class_get_all_by_name()
        self._mock_quota_class_get_default()

    def test_get_project_quotas(self):
        self._mock_get_by_project()
        self._mock_volume_type_get_all()
        self._mock_allocated_get_all_by_project()
        result = self.driver.get_project_quotas(
            FakeContext('test_project', 'test_class'),
            quota.QUOTAS.resources, 'test_project')

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_allocated_get_all_by_project',
                          'quota_class_get_all_by_name',
                          'quota_class_get_defaults', ], self.calls)
        self.assertEqual(dict(volumes=dict(limit=10,
                                           in_use=2,
                                           reserved=0, ),
                              snapshots=dict(limit=10,
                                             in_use=2,
                                             reserved=0, ),
                              gigabytes=dict(limit=50,
                                             in_use=10,
                                             reserved=0, ),
                              backups=dict(limit=10,
                                           in_use=2,
                                           reserved=0, ),
                              backup_gigabytes=dict(limit=50,
                                                    in_use=10,
                                                    reserved=0, ),
                              per_volume_gigabytes=dict(in_use=0,
                                                        limit=-1,
                                                        reserved= 0)
                              ), result)

    @mock.patch('cinder.quota.db.quota_get_all_by_project')
    @mock.patch('cinder.quota.db.quota_class_get_defaults')
    def test_get_project_quotas_lazy_load_defaults(
            self, mock_defaults, mock_quotas):
        mock_quotas.return_value = self._default_quotas_non_child
        self.driver.get_project_quotas(
            FakeContext('test_project', None),
            quota.QUOTAS.resources, 'test_project', usages=False)
        # Shouldn't load a project's defaults if all the quotas are already
        # defined in the DB
        self.assertFalse(mock_defaults.called)

        mock_quotas.return_value = {}
        self.driver.get_project_quotas(
            FakeContext('test_project', None),
            quota.QUOTAS.resources, 'test_project', usages=False)
        self.assertTrue(mock_defaults.called)

    def test_get_root_project_with_subprojects_quotas(self):
        self._mock_get_by_project()
        self._mock_volume_type_get_all()
        self._mock_allocated_get_all_by_project(allocated_quota=True)
        result = self.driver.get_project_quotas(
            FakeContext('test_project', None),
            quota.QUOTAS.resources, 'test_project')

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_allocated_get_all_by_project',
                          'quota_class_get_defaults', ], self.calls)
        self.assertEqual(dict(volumes=dict(limit=10,
                                           in_use=2,
                                           reserved=0,
                                           allocated=3, ),
                              snapshots=dict(limit=10,
                                             in_use=2,
                                             reserved=0,
                                             allocated=0, ),
                              gigabytes=dict(limit=50,
                                             in_use=10,
                                             reserved=0,
                                             allocated=0, ),
                              backups=dict(limit=10,
                                           in_use=2,
                                           reserved=0,
                                           allocated=0, ),
                              backup_gigabytes=dict(limit=50,
                                                    in_use=10,
                                                    reserved=0,
                                                    allocated=0, ),
                              per_volume_gigabytes=dict(in_use=0,
                                                        limit=-1,
                                                        reserved=0,
                                                        allocated=0)
                              ), result)

    def test_get_project_quotas_alt_context_no_class(self):
        self._mock_get_by_project()
        self._mock_volume_type_get_all()
        result = self.driver.get_project_quotas(
            FakeContext('other_project', 'other_class'),
            quota.QUOTAS.resources, 'test_project')

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_class_get_defaults', ], self.calls)
        self.assertEqual(dict(volumes=dict(limit=10,
                                           in_use=2,
                                           reserved=0, ),
                              snapshots=dict(limit=10,
                                             in_use=2,
                                             reserved=0, ),
                              gigabytes=dict(limit=50,
                                             in_use=10,
                                             reserved=0, ),
                              backups=dict(limit=10,
                                           in_use=2,
                                           reserved=0, ),
                              backup_gigabytes=dict(limit=50,
                                                    in_use=10,
                                                    reserved=0, ),
                              per_volume_gigabytes=dict(in_use=0,
                                                        limit=-1,
                                                        reserved=0)
                              ), result)

    def test_get_project_quotas_alt_context_with_class(self):
        self._mock_get_by_project()
        self._mock_volume_type_get_all()
        result = self.driver.get_project_quotas(
            FakeContext('other_project', 'other_class'),
            quota.QUOTAS.resources, 'test_project', quota_class='test_class')

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_class_get_all_by_name',
                          'quota_class_get_defaults', ], self.calls)
        self.assertEqual(dict(volumes=dict(limit=10,
                                           in_use=2,
                                           reserved=0, ),
                              snapshots=dict(limit=10,
                                             in_use=2,
                                             reserved=0, ),
                              gigabytes=dict(limit=50,
                                             in_use=10,
                                             reserved=0, ),
                              backups=dict(limit=10,
                                           in_use=2,
                                           reserved=0, ),
                              backup_gigabytes=dict(limit=50,
                                                    in_use=10,
                                                    reserved=0, ),
                              per_volume_gigabytes=dict(in_use=0,
                                                        limit=-1,
                                                        reserved= 0)),
                         result)

    def test_get_project_quotas_no_defaults(self):
        self._mock_get_by_project()
        self._mock_volume_type_get_all()
        result = self.driver.get_project_quotas(
            FakeContext('test_project', 'test_class'),
            quota.QUOTAS.resources, 'test_project', defaults=False)

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_class_get_all_by_name'], self.calls)
        self.assertEqual(dict(backups=dict(limit=10,
                                           in_use=2,
                                           reserved=0, ),
                              backup_gigabytes=dict(limit=50,
                                                    in_use=10,
                                                    reserved=0, ),
                              gigabytes=dict(limit=50,
                                             in_use=10,
                                             reserved=0, ),
                              snapshots=dict(limit=10,
                                             in_use=2,
                                             reserved=0, ),
                              volumes=dict(limit=10,
                                           in_use=2,
                                           reserved=0, ),

                              ), result)

    def test_get_project_quotas_no_usages(self):
        self._mock_get_by_project()
        self._mock_volume_type_get_all()
        result = self.driver.get_project_quotas(
            FakeContext('test_project', 'test_class'),
            quota.QUOTAS.resources, 'test_project', usages=False)

        self.assertEqual(['quota_get_all_by_project',
                          'quota_class_get_all_by_name',
                          'quota_class_get_defaults', ], self.calls)
        self.assertEqual(dict(volumes=dict(limit=10, ),
                              snapshots=dict(limit=10, ),
                              backups=dict(limit=10, ),
                              gigabytes=dict(limit=50, ),
                              backup_gigabytes=dict(limit=50, ),
                              per_volume_gigabytes=dict(limit=-1, )), result)

    def _mock_get_project_quotas(self):
        def fake_get_project_quotas(context, resources, project_id,
                                    quota_class=None, defaults=True,
                                    usages=True, parent_project_id=None):
            self.calls.append('get_project_quotas')
            return {k: dict(limit=v.default) for k, v in resources.items()}

        self.mock_object(self.driver, 'get_project_quotas',
                         fake_get_project_quotas)

    def test_get_quotas_has_sync_unknown(self):
        self._mock_get_project_quotas()
        self.assertRaises(exception.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS.resources,
                          ['unknown'], True)
        self.assertEqual([], self.calls)

    def test_get_quotas_no_sync_unknown(self):
        self._mock_get_project_quotas()
        self.assertRaises(exception.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS.resources,
                          ['unknown'], False)
        self.assertEqual([], self.calls)

    def test_get_quotas_has_sync_no_sync_resource(self):
        self._mock_get_project_quotas()
        self.assertRaises(exception.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS.resources,
                          ['metadata_items'], True)
        self.assertEqual([], self.calls)

    def test_get_quotas_no_sync_has_sync_resource(self):
        self._mock_get_project_quotas()
        self.assertRaises(exception.QuotaResourceUnknown,
                          self.driver._get_quotas,
                          None, quota.QUOTAS.resources,
                          ['volumes'], False)
        self.assertEqual([], self.calls)

    def test_get_quotas_has_sync(self):
        self._mock_get_project_quotas()
        result = self.driver._get_quotas(FakeContext('test_project',
                                                     'test_class'),
                                         quota.QUOTAS.resources,
                                         ['volumes', 'gigabytes'],
                                         True)

        self.assertEqual(['get_project_quotas'], self.calls)
        self.assertEqual(dict(volumes=10, gigabytes=1000, ), result)

    def _mock_quota_reserve(self):
        def fake_quota_reserve(context, resources, quotas, deltas, expire,
                               until_refresh, max_age, project_id=None):
            self.calls.append(('quota_reserve', expire, until_refresh,
                               max_age))
            return ['resv-1', 'resv-2', 'resv-3']
        self.mock_object(db, 'quota_reserve', fake_quota_reserve)

    def test_reserve_bad_expire(self):
        self._mock_get_project_quotas()
        self._mock_quota_reserve()
        self.assertRaises(exception.InvalidReservationExpiration,
                          self.driver.reserve,
                          FakeContext('test_project', 'test_class'),
                          quota.QUOTAS.resources,
                          dict(volumes=2), expire='invalid')
        self.assertEqual([], self.calls)

    def test_reserve_default_expire(self):
        self._mock_get_project_quotas()
        self._mock_quota_reserve()
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2))

        expire = timeutils.utcnow() + datetime.timedelta(seconds=86400)
        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 0, 0), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def test_reserve_int_expire(self):
        self._mock_get_project_quotas()
        self._mock_quota_reserve()
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2), expire=3600)

        expire = timeutils.utcnow() + datetime.timedelta(seconds=3600)
        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 0, 0), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def test_reserve_timedelta_expire(self):
        self._mock_get_project_quotas()
        self._mock_quota_reserve()
        expire_delta = datetime.timedelta(seconds=60)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2), expire=expire_delta)

        expire = timeutils.utcnow() + expire_delta
        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 0, 0), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def test_reserve_datetime_expire(self):
        self._mock_get_project_quotas()
        self._mock_quota_reserve()
        expire = timeutils.utcnow() + datetime.timedelta(seconds=120)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2), expire=expire)

        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 0, 0), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def test_reserve_until_refresh(self):
        self._mock_get_project_quotas()
        self._mock_quota_reserve()
        self.flags(until_refresh=500)
        expire = timeutils.utcnow() + datetime.timedelta(seconds=120)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2), expire=expire)

        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 500, 0), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def test_reserve_max_age(self):
        self._mock_get_project_quotas()
        self._mock_quota_reserve()
        self.flags(max_age=86400)
        expire = timeutils.utcnow() + datetime.timedelta(seconds=120)
        result = self.driver.reserve(FakeContext('test_project', 'test_class'),
                                     quota.QUOTAS.resources,
                                     dict(volumes=2), expire=expire)

        self.assertEqual(['get_project_quotas',
                          ('quota_reserve', expire, 0, 86400), ], self.calls)
        self.assertEqual(['resv-1', 'resv-2', 'resv-3'], result)

    def _mock_quota_destroy_by_project(self):
        def fake_quota_destroy_by_project(context, project_id):
            self.calls.append(('quota_destroy_by_project', project_id))
            return None
        self.mock_object(sqa_api, 'quota_destroy_by_project',
                         fake_quota_destroy_by_project)

    def test_destroy_quota_by_project(self):
        self._mock_quota_destroy_by_project()
        self.driver.destroy_by_project(FakeContext('test_project',
                                                   'test_class'),
                                       'test_project')
        self.assertEqual([('quota_destroy_by_project', ('test_project')), ],
                         self.calls)


class NestedDbQuotaDriverBaseTestCase(DbQuotaDriverBaseTestCase):
    def setUp(self):
        super(NestedDbQuotaDriverBaseTestCase, self).setUp()
        self.context = context.RequestContext('user_id',
                                              'project_id',
                                              is_admin=True,
                                              auth_token="fake_token")
        self.auth_url = 'http://localhost:5000'
        self._child_proj_id = 'child_id'
        self._non_child_proj_id = 'non_child_id'

        keystone_mock = mock.Mock()
        keystone_mock.version = 'v3'

        class FakeProject(object):
            def __init__(self, parent_id):
                self.parent_id = parent_id
                self.parents = {parent_id: None}
                self.domain_id = 'default'

        def fake_get_project(project_id, subtree_as_ids=False,
                             parents_as_ids=False):
            # Enable imitation of projects with and without parents
            if project_id == self._child_proj_id:
                return FakeProject('parent_id')
            else:
                return FakeProject(None)

        keystone_mock.projects.get.side_effect = fake_get_project

        def _keystone_mock(self):
            return keystone_mock

        keystone_patcher = mock.patch('cinder.quota_utils._keystone_client',
                                      _keystone_mock)
        keystone_patcher.start()
        self.addCleanup(keystone_patcher.stop)

        self.fixture = self.useFixture(config_fixture.Config(CONF))
        self.fixture.config(auth_uri=self.auth_url, group='keystone_authtoken')
        self.driver = quota.NestedDbQuotaDriver()

    def _mock_get_by_subproject(self):
        def fake_qgabp(context, project_id):
            self.calls.append('quota_get_all_by_project')
            return dict(volumes=10, gigabytes=50, reserved=0)

        def fake_qugabp(context, project_id):
            self.calls.append('quota_usage_get_all_by_project')
            return dict(volumes=dict(in_use=2, reserved=0),
                        gigabytes=dict(in_use=10, reserved=0))

        self.mock_object(db, 'quota_get_all_by_project', fake_qgabp)
        self.mock_object(db, 'quota_usage_get_all_by_project', fake_qugabp)

        self._mock_quota_class_get_all_by_name()


class NestedDbQuotaDriverTestCase(NestedDbQuotaDriverBaseTestCase):
    def test_get_defaults(self):
        self._mock_volume_type_get_all()

        # Test for child project defaults
        result = self.driver.get_defaults(self.context,
                                          quota.QUOTAS.resources,
                                          self._child_proj_id)
        self.assertEqual(self._default_quotas_child, result)

        # Test for non-child project defaults
        result = self.driver.get_defaults(self.context,
                                          quota.QUOTAS.resources,
                                          self._non_child_proj_id)
        self.assertEqual(self._default_quotas_non_child, result)

    def test_subproject_enforce_defaults(self):
        # Non-child defaults should allow volume to get created
        self.driver.reserve(self.context,
                            quota.QUOTAS.resources,
                            {'volumes': 1, 'gigabytes': 1},
                            project_id=self._non_child_proj_id)

        # Child defaults should not allow volume to be created
        self.assertRaises(exception.OverQuota,
                          self.driver.reserve, self.context,
                          quota.QUOTAS.resources,
                          {'volumes': 1, 'gigabytes': 1},
                          project_id=self._child_proj_id)

    def test_get_subproject_quotas(self):
        self._mock_get_by_subproject()
        self._mock_volume_type_get_all()
        self._mock_allocated_get_all_by_project(allocated_quota=True)
        result = self.driver.get_project_quotas(
            self.context,
            quota.QUOTAS.resources, self._child_proj_id)

        self.assertEqual(['quota_get_all_by_project',
                          'quota_usage_get_all_by_project',
                          'quota_allocated_get_all_by_project', ], self.calls)
        self.assertEqual(dict(volumes=dict(limit=10,
                                           in_use=2,
                                           reserved=0,
                                           allocated=3, ),
                              snapshots=dict(limit=0,
                                             in_use=0,
                                             reserved=0,
                                             allocated=0, ),
                              gigabytes=dict(limit=50,
                                             in_use=10,
                                             reserved=0,
                                             allocated=0, ),
                              backups=dict(limit=0,
                                           in_use=0,
                                           reserved=0,
                                           allocated=0, ),
                              backup_gigabytes=dict(limit=0,
                                                    in_use=0,
                                                    reserved=0,
                                                    allocated=0, ),
                              per_volume_gigabytes=dict(in_use=0,
                                                        limit=0,
                                                        reserved=0,
                                                        allocated=0)
                              ), result)


class NestedQuotaValidation(NestedDbQuotaDriverBaseTestCase):
    def setUp(self):
        super(NestedQuotaValidation, self).setUp()
        r"""
        Quota hierarchy setup like so
        +-----------+
        |           |
        |     A     |
        |    / \    |
        |   B   C   |
        |  /        |
        | D         |
        +-----------+
        """
        self.project_tree = {'A': {'B': {'D': None}, 'C': None}}
        self.proj_vals = {
            'A': {'limit': 7, 'in_use': 1, 'alloc': 6},
            'B': {'limit': 3, 'in_use': 1, 'alloc': 2},
            'D': {'limit': 2, 'in_use': 0},
            'C': {'limit': 3, 'in_use': 3},
        }

        # Just using one resource currently for simplicity of test
        self.resources = {'volumes': quota.ReservableResource(
            'volumes', '_sync_volumes', 'quota_volumes')}

        to_patch = [('cinder.db.quota_allocated_get_all_by_project',
                     self._fake_quota_allocated_get_all_by_project),
                    ('cinder.db.quota_get_all_by_project',
                     self._fake_quota_get_all_by_project),
                    ('cinder.db.quota_usage_get_all_by_project',
                     self._fake_quota_usage_get_all_by_project)]

        for patch_path, patch_obj in to_patch:
            patcher = mock.patch(patch_path, patch_obj)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _fake_quota_get_all_by_project(self, context, project_id):
        return {'volumes': self.proj_vals[project_id]['limit']}

    def _fake_quota_usage_get_all_by_project(self, context, project_id):
        return {'volumes': self.proj_vals[project_id]}

    def _fake_quota_allocated_get_all_by_project(self, context, project_id,
                                                 session=None):
        ret = {'project_id': project_id}
        proj_val = self.proj_vals[project_id]
        if 'alloc' in proj_val:
            ret['volumes'] = proj_val['alloc']
        return ret

    def test_validate_nested_quotas(self):
        self.driver.validate_nested_setup(self.context,
                                          self.resources, self.project_tree)

        # Fail because 7 - 2 < 3 + 3
        self.proj_vals['A']['in_use'] = 2
        self.assertRaises(exception.InvalidNestedQuotaSetup,
                          self.driver.validate_nested_setup,
                          self.context,
                          self.resources, self.project_tree)
        self.proj_vals['A']['in_use'] = 1

        # Fail because 7 - 1 < 3 + 7
        self.proj_vals['C']['limit'] = 7
        self.assertRaises(exception.InvalidNestedQuotaSetup,
                          self.driver.validate_nested_setup,
                          self.context,
                          self.resources, self.project_tree)
        self.proj_vals['C']['limit'] = 3

        # Fail because 3 < 4
        self.proj_vals['D']['limit'] = 4
        self.assertRaises(exception.InvalidNestedQuotaSetup,
                          self.driver.validate_nested_setup,
                          self.context,
                          self.resources, self.project_tree)
        self.proj_vals['D']['limit'] = 2

    def test_validate_nested_quotas_usage_over_limit(self):
        self.proj_vals['D']['in_use'] = 5
        self.assertRaises(exception.InvalidNestedQuotaSetup,
                          self.driver.validate_nested_setup,
                          self.context, self.resources, self.project_tree)

    def test_validate_nested_quota_bad_allocated_quotas(self):
        self.proj_vals['A']['alloc'] = 5
        self.proj_vals['B']['alloc'] = 8
        self.assertRaises(exception.InvalidNestedQuotaSetup,
                          self.driver.validate_nested_setup,
                          self.context, self.resources, self.project_tree)

    def test_validate_nested_quota_negative_child_limits(self):
        # Redefining the project limits with -1, doing it all in this test
        # for readability
        self.proj_vals = {
            'A': {'limit': 8, 'in_use': 1},
            'B': {'limit': -1, 'in_use': 3},
            'D': {'limit': 4, 'in_use': 0},
            'C': {'limit': 2, 'in_use': 2},
        }

        # A's child usage is 3 (from B) + 4 (from D) + 2 (from C) = 9
        self.assertRaises(exception.InvalidNestedQuotaSetup,
                          self.driver.validate_nested_setup,
                          self.context, self.resources, self.project_tree)

        self.proj_vals['D']['limit'] = 2
        self.driver.validate_nested_setup(
            self.context, self.resources, self.project_tree,
            fix_allocated_quotas=True)

    def test_get_cur_project_allocated(self):
        # Redefining the project limits with -1, doing it all in this test
        # for readability
        self.proj_vals = {
            # Allocated are here to simulate a bad existing value
            'A': {'limit': 8, 'in_use': 1, 'alloc': 6},
            'B': {'limit': -1, 'in_use': 3, 'alloc': 2},
            'D': {'limit': 1, 'in_use': 0},
            'C': {'limit': 2, 'in_use': 2},
        }

        self.driver._allocated = {}
        allocated_a = self.driver._get_cur_project_allocated(
            self.context, self.resources['volumes'],
            self.project_tree)

        # A's allocated will be:
        #   2 (from C's limit) + 3 (from B's in-use) + 1 (from D's limit) = 6
        self.assertEqual(6, allocated_a)

        # B's allocated value should also be calculated and cached as part
        # of A's calculation
        self.assertEqual(1, self.driver._allocated['B']['volumes'])


class FakeSession(object):
    def begin(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        return False

    def query(self, *args, **kwargs):
        pass


class FakeUsage(sqa_models.QuotaUsage):
    def save(self, *args, **kwargs):
        pass


class QuotaReserveSqlAlchemyTestCase(test.TestCase):
    # cinder.db.sqlalchemy.api.quota_reserve is so complex it needs its
    # own test case, and since it's a quota manipulator, this is the
    # best place to put it...

    def setUp(self):
        super(QuotaReserveSqlAlchemyTestCase, self).setUp()

        self.sync_called = set()

        def make_sync(res_name):
            def fake_sync(context, project_id, volume_type_id=None,
                          volume_type_name=None, session=None):
                self.sync_called.add(res_name)
                if res_name in self.usages:
                    if self.usages[res_name].in_use < 0:
                        return {res_name: 2}
                    else:
                        return {res_name: self.usages[res_name].in_use - 1}
                return {res_name: 0}
            return fake_sync

        self.resources = {}
        QUOTA_SYNC_FUNCTIONS = {}
        for res_name in ('volumes', 'gigabytes'):
            res = quota.ReservableResource(res_name, '_sync_%s' % res_name)
            QUOTA_SYNC_FUNCTIONS['_sync_%s' % res_name] = make_sync(res_name)
            self.resources[res_name] = res

        self.mock_object(sqa_api, 'QUOTA_SYNC_FUNCTIONS', QUOTA_SYNC_FUNCTIONS)
        self.expire = timeutils.utcnow() + datetime.timedelta(seconds=3600)

        self.usages = {}
        self.usages_created = {}
        self.reservations_created = {}

        def fake_get_session():
            return FakeSession()

        def fake_get_quota_usages(context, session, project_id):
            return self.usages.copy()

        def fake_quota_usage_create(context, project_id, resource, in_use,
                                    reserved, until_refresh, session=None,
                                    save=True):
            quota_usage_ref = self._make_quota_usage(
                project_id, resource, in_use, reserved, until_refresh,
                timeutils.utcnow(), timeutils.utcnow())

            self.usages_created[resource] = quota_usage_ref

            return quota_usage_ref

        def fake_reservation_create(context, uuid, usage_id, project_id,
                                    resource, delta, expire, session=None,
                                    allocated_id=None):
            reservation_ref = self._make_reservation(
                uuid, usage_id, project_id, resource, delta, expire,
                timeutils.utcnow(), timeutils.utcnow(), allocated_id)

            self.reservations_created[resource] = reservation_ref

            return reservation_ref

        self.mock_object(sqa_api, 'get_session',
                         fake_get_session)
        self.mock_object(sqa_api, '_get_quota_usages',
                         fake_get_quota_usages)
        self.mock_object(sqa_api, '_quota_usage_create',
                         fake_quota_usage_create)
        self.mock_object(sqa_api, '_reservation_create',
                         fake_reservation_create)

        patcher = mock.patch.object(timeutils, 'utcnow')
        self.addCleanup(patcher.stop)
        self.mock_utcnow = patcher.start()
        self.mock_utcnow.return_value = datetime.datetime.utcnow()

    def _make_quota_usage(self, project_id, resource, in_use, reserved,
                          until_refresh, created_at, updated_at):
        quota_usage_ref = FakeUsage()
        quota_usage_ref.id = len(self.usages) + len(self.usages_created)
        quota_usage_ref.project_id = project_id
        quota_usage_ref.resource = resource
        quota_usage_ref.in_use = in_use
        quota_usage_ref.reserved = reserved
        quota_usage_ref.until_refresh = until_refresh
        quota_usage_ref.created_at = created_at
        quota_usage_ref.updated_at = updated_at
        quota_usage_ref.deleted_at = None
        quota_usage_ref.deleted = False

        return quota_usage_ref

    def init_usage(self, project_id, resource, in_use, reserved,
                   until_refresh=None, created_at=None, updated_at=None):
        if created_at is None:
            created_at = timeutils.utcnow()
        if updated_at is None:
            updated_at = timeutils.utcnow()

        quota_usage_ref = self._make_quota_usage(project_id, resource, in_use,
                                                 reserved, until_refresh,
                                                 created_at, updated_at)

        self.usages[resource] = quota_usage_ref

    def compare_usage(self, usage_dict, expected):
        for usage in expected:
            resource = usage['resource']
            for key, value in usage.items():
                actual = getattr(usage_dict[resource], key)
                self.assertEqual(value, actual,
                                 "%s != %s on usage for resource %s" %
                                 (actual, value, resource))

    def _make_reservation(self, uuid, usage_id, project_id, resource,
                          delta, expire, created_at, updated_at, alloc_id):
        reservation_ref = sqa_models.Reservation()
        reservation_ref.id = len(self.reservations_created)
        reservation_ref.uuid = uuid
        reservation_ref.usage_id = usage_id
        reservation_ref.project_id = project_id
        reservation_ref.resource = resource
        reservation_ref.delta = delta
        reservation_ref.expire = expire
        reservation_ref.created_at = created_at
        reservation_ref.updated_at = updated_at
        reservation_ref.deleted_at = None
        reservation_ref.deleted = False
        reservation_ref.allocated_id = alloc_id

        return reservation_ref

    def compare_reservation(self, reservations, expected):
        reservations = set(reservations)
        for resv in expected:
            resource = resv['resource']
            resv_obj = self.reservations_created[resource]

            self.assertIn(resv_obj.uuid, reservations)
            reservations.discard(resv_obj.uuid)

            for key, value in resv.items():
                actual = getattr(resv_obj, key)
                self.assertEqual(value, actual,
                                 "%s != %s on reservation for resource %s" %
                                 (actual, value, resource))

        self.assertEqual(0, len(reservations))

    def _mock_allocated_get_all_by_project(self, allocated_quota=False):
        def fake_qagabp(context, project_id, session=None):
            self.assertEqual('test_project', project_id)
            self.assertIsNotNone(session)
            if allocated_quota:
                return dict(project_id=project_id, volumes=3,
                            gigabytes = 2 * 1024)
            return dict(project_id=project_id)

        self.mock_object(sqa_api, 'quota_allocated_get_all_by_project',
                         fake_qagabp)

    def test_quota_reserve_with_allocated(self):
        context = FakeContext('test_project', 'test_class')
        # Allocated quota for volume will be updated for 3
        self._mock_allocated_get_all_by_project(allocated_quota=True)
        # Quota limited for volume updated for 10
        quotas = dict(volumes=10,
                      gigabytes=10 * 1024, )
        # Try reserve 7 volumes
        deltas = dict(volumes=7,
                      gigabytes=2 * 1024, )
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 5, 0)
        # The reservation works
        self.compare_reservation(
            result,
            [dict(resource='volumes',
                  usage_id=self.usages_created['volumes'],
                  project_id='test_project',
                  delta=7),
             dict(resource='gigabytes',
                  usage_id=self.usages_created['gigabytes'],
                  delta=2 * 1024), ])

        # But if we try reserve 8 volumes(more free quota that we have)
        deltas = dict(volumes=8,
                      gigabytes=2 * 1024, )

        self.assertRaises(exception.OverQuota,
                          sqa_api.quota_reserve,
                          context, self.resources, quotas,
                          deltas, self.expire, 0, 0)

    def test_quota_reserve_create_usages(self):
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5,
                      gigabytes=10 * 1024, )
        deltas = dict(volumes=2,
                      gigabytes=2 * 1024, )
        self._mock_allocated_get_all_by_project()
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, 0)

        self.assertEqual(set(['volumes', 'gigabytes']), self.sync_called)
        self.compare_usage(self.usages_created,
                           [dict(resource='volumes',
                                 project_id='test_project',
                                 in_use=0,
                                 reserved=2,
                                 until_refresh=None),
                            dict(resource='gigabytes',
                                 project_id='test_project',
                                 in_use=0,
                                 reserved=2 * 1024,
                                 until_refresh=None), ])
        self.compare_reservation(
            result,
            [dict(resource='volumes',
                  usage_id=self.usages_created['volumes'],
                  project_id='test_project',
                  delta=2),
             dict(resource='gigabytes',
                  usage_id=self.usages_created['gigabytes'],
                  delta=2 * 1024), ])

    def test_quota_reserve_negative_in_use(self):
        self.init_usage('test_project', 'volumes', -1, 0, until_refresh=1)
        self.init_usage('test_project', 'gigabytes', -1, 0, until_refresh=1)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5,
                      gigabytes=10 * 1024, )
        deltas = dict(volumes=2,
                      gigabytes=2 * 1024, )
        self._mock_allocated_get_all_by_project()
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 5, 0)

        self.assertEqual(set(['volumes', 'gigabytes']), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=2,
                                              reserved=2,
                                              until_refresh=5),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=2,
                                              reserved=2 * 1024,
                                              until_refresh=5), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=2 * 1024), ])

    def test_quota_reserve_until_refresh(self):
        self.init_usage('test_project', 'volumes', 3, 0, until_refresh=1)
        self.init_usage('test_project', 'gigabytes', 3, 0, until_refresh=1)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=2, gigabytes=2 * 1024, )
        self._mock_allocated_get_all_by_project()
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 5, 0)

        self.assertEqual(set(['volumes', 'gigabytes']), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=2,
                                              reserved=2,
                                              until_refresh=5),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=2,
                                              reserved=2 * 1024,
                                              until_refresh=5), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=2 * 1024), ])

    def test_quota_reserve_max_age(self):
        max_age = 3600
        record_created = (timeutils.utcnow() -
                          datetime.timedelta(seconds=max_age))
        self.init_usage('test_project', 'volumes', 3, 0,
                        created_at=record_created, updated_at=record_created)
        self.init_usage('test_project', 'gigabytes', 3, 0,
                        created_at=record_created, updated_at=record_created)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=2, gigabytes=2 * 1024, )
        self._mock_allocated_get_all_by_project()
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, max_age)

        self.assertEqual(set(['volumes', 'gigabytes']), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=2,
                                              reserved=2,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=2,
                                              reserved=2 * 1024,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=2 * 1024), ])

    def test_quota_reserve_max_age_negative(self):
        max_age = 3600
        record_created = (timeutils.utcnow() +
                          datetime.timedelta(seconds=max_age))
        self.init_usage('test_project', 'volumes', 3, 0,
                        created_at=record_created, updated_at=record_created)
        self.init_usage('test_project', 'gigabytes', 3, 0,
                        created_at=record_created, updated_at=record_created)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=2, gigabytes=2 * 1024, )
        self._mock_allocated_get_all_by_project()
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, max_age)

        self.assertEqual(set(), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=3,
                                              reserved=2,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=3,
                                              reserved=2 * 1024,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=2 * 1024), ])

    def test_quota_reserve_no_refresh(self):
        self.init_usage('test_project', 'volumes', 3, 0)
        self.init_usage('test_project', 'gigabytes', 3, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=2, gigabytes=2 * 1024, )
        self._mock_allocated_get_all_by_project()
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, 0)

        self.assertEqual(set([]), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=3,
                                              reserved=2,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=3,
                                              reserved=2 * 1024,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=2 * 1024), ])

    def test_quota_reserve_unders(self):
        self.init_usage('test_project', 'volumes', 1, 0)
        self.init_usage('test_project', 'gigabytes', 1 * 1024, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=-2, gigabytes=-2 * 1024, )
        self._mock_allocated_get_all_by_project()
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, 0)

        self.assertEqual(set([]), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=1,
                                              reserved=0,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=1 * 1024,
                                              reserved=0,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=-2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       delta=-2 * 1024), ])

    def test_quota_reserve_overs(self):
        self.init_usage('test_project', 'volumes', 4, 0)
        self.init_usage('test_project', 'gigabytes', 10 * 1024, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=2, gigabytes=2 * 1024, )
        self._mock_allocated_get_all_by_project()
        self.assertRaises(exception.OverQuota,
                          sqa_api.quota_reserve,
                          context, self.resources, quotas,
                          deltas, self.expire, 0, 0)

        self.assertEqual(set([]), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=4,
                                              reserved=0,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=10 * 1024,
                                              reserved=0,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.assertEqual({}, self.reservations_created)

    def test_quota_reserve_reduction(self):
        self.init_usage('test_project', 'volumes', 10, 0)
        self.init_usage('test_project', 'gigabytes', 20 * 1024, 0)
        context = FakeContext('test_project', 'test_class')
        quotas = dict(volumes=5, gigabytes=10 * 1024, )
        deltas = dict(volumes=-2, gigabytes=-2 * 1024, )
        self._mock_allocated_get_all_by_project()
        result = sqa_api.quota_reserve(context, self.resources, quotas,
                                       deltas, self.expire, 0, 0)

        self.assertEqual(set([]), self.sync_called)
        self.compare_usage(self.usages, [dict(resource='volumes',
                                              project_id='test_project',
                                              in_use=10,
                                              reserved=0,
                                              until_refresh=None),
                                         dict(resource='gigabytes',
                                              project_id='test_project',
                                              in_use=20 * 1024,
                                              reserved=0,
                                              until_refresh=None), ])
        self.assertEqual({}, self.usages_created)
        self.compare_reservation(result,
                                 [dict(resource='volumes',
                                       usage_id=self.usages['volumes'],
                                       project_id='test_project',
                                       delta=-2),
                                  dict(resource='gigabytes',
                                       usage_id=self.usages['gigabytes'],
                                       project_id='test_project',
                                       delta=-2 * 1024), ])


class QuotaVolumeTypeReservationTestCase(test.TestCase):

    def setUp(self):
        super(QuotaVolumeTypeReservationTestCase, self).setUp()

        self.volume_type_name = CONF.default_volume_type
        self.volume_type = db.volume_type_create(
            context.get_admin_context(),
            dict(name=self.volume_type_name))

    @mock.patch.object(quota.QUOTAS, 'reserve')
    @mock.patch.object(quota.QUOTAS, 'add_volume_type_opts')
    def test_volume_type_reservation(self,
                                     mock_add_volume_type_opts,
                                     mock_reserve):
        my_context = FakeContext('MyProject', None)
        volume = {'name': 'my_vol_name',
                  'id': 'my_vol_id',
                  'size': '1',
                  'project_id': 'vol_project_id',
                  }
        reserve_opts = {'volumes': 1, 'gigabytes': volume['size']}
        quota_utils.get_volume_type_reservation(my_context,
                                                volume,
                                                self.volume_type['id'])
        mock_add_volume_type_opts.assert_called_once_with(
            my_context,
            reserve_opts,
            self.volume_type['id'])
        mock_reserve.assert_called_once_with(my_context,
                                             project_id='vol_project_id',
                                             gigabytes='1',
                                             volumes=1)

    @mock.patch.object(quota.QUOTAS, 'reserve')
    def test_volume_type_reservation_with_type_only(self, mock_reserve):
        my_context = FakeContext('MyProject', None)
        volume = {'name': 'my_vol_name',
                  'id': 'my_vol_id',
                  'size': '1',
                  'project_id': 'vol_project_id',
                  }
        quota_utils.get_volume_type_reservation(my_context,
                                                volume,
                                                self.volume_type['id'],
                                                reserve_vol_type_only=True)
        vtype_volume_quota = "%s_%s" % ('volumes', self.volume_type['name'])
        vtype_size_quota = "%s_%s" % ('gigabytes', self.volume_type['name'])
        reserve_opts = {vtype_volume_quota: 1,
                        vtype_size_quota: volume['size']}
        mock_reserve.assert_called_once_with(my_context,
                                             project_id='vol_project_id',
                                             **reserve_opts)
