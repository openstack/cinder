# Copyright 2015 IBM Corp.
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

from oslo_versionedobjects import fixture

from cinder import db
from cinder import objects
from cinder.objects import base
from cinder import test


# NOTE: The hashes in this list should only be changed if they come with a
# corresponding version bump in the affected objects.
object_data = {
    'Backup': '1.4-c50f7a68bb4c400dd53dd219685b3992',
    'BackupImport': '1.4-c50f7a68bb4c400dd53dd219685b3992',
    'BackupList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'CGSnapshot': '1.0-3212ac2b4c2811b7134fb9ba2c49ff74',
    'CGSnapshotList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'ConsistencyGroup': '1.2-ff7638e03ae7a3bb7a43a6c5c4d0c94a',
    'ConsistencyGroupList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'Service': '1.3-d7c1e133791c9d766596a0528fc9a12f',
    'ServiceList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'Snapshot': '1.1-37966f7141646eb29e9ad5298ff2ca8a',
    'SnapshotList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'Volume': '1.3-15ff1f42d4e8eb321aa8217dd46aa1e1',
    'VolumeList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'VolumeAttachment': '1.0-b30dacf62b2030dd83d8a1603f1064ff',
    'VolumeAttachmentList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'VolumeType': '1.1-6673dd9ce7c27e9c85279afb20833877',
    'VolumeTypeList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
}


class TestObjectVersions(test.TestCase):

    def test_versions(self):
        checker = fixture.ObjectVersionChecker(
            base.CinderObjectRegistry.obj_classes())
        expected, actual = checker.test_hashes(object_data)
        self.assertEqual(expected, actual,
                         'Some objects have changed; please make sure the '
                         'versions have been bumped, and then update their '
                         'hashes in the object_data map in this test module.')

    def test_versions_history(self):
        classes = base.CinderObjectRegistry.obj_classes()
        versions = base.OBJ_VERSIONS.get_current_versions()
        expected = {}
        actual = {}
        for name, cls in classes.items():
            if name not in versions:
                expected[name] = cls[0].VERSION
            elif cls[0].VERSION != versions[name]:
                expected[name] = cls[0].VERSION
                actual[name] = versions[name]

        self.assertEqual(expected, actual,
                         'Some objects versions have changed; please make '
                         'sure a new objects history version was added in '
                         'cinder.objects.base.OBJ_VERSIONS.')

    def test_object_nullable_match_db(self):
        # This test is to keep nullable of every field in corresponding
        # db model and object match.
        def _check_table_matched(db_model, cls):
            for column in db_model.__table__.columns:
                if column.name in cls.fields:
                    self.assertEqual(
                        column.nullable,
                        cls.fields[column.name].nullable,
                        'Column %(c)s in table %(t)s not match.'
                        % {'c': column.name,
                           't': name})

        classes = base.CinderObjectRegistry.obj_classes()
        for name, cls in classes.items():
            if not issubclass(cls[0], base.ObjectListBase):
                db_model = db.get_model_for_versioned_object(cls[0])
                _check_table_matched(db_model, cls[0])

    def test_obj_make_compatible(self):
        # Go through all of the object classes and run obj_to_primitive() with
        # a target version of all previous minor versions. It doesn't test
        # the converted data, but at least ensures the method doesn't blow
        # up on something simple.
        init_args = {}
        init_kwargs = {objects.Snapshot: {'context': 'ctxt'}}
        checker = fixture.ObjectVersionChecker(
            base.CinderObjectRegistry.obj_classes())
        checker.test_compatibility_routines(init_args=init_args,
                                            init_kwargs=init_kwargs)
