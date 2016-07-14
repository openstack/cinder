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
from cinder.objects import base
from cinder import test


# NOTE: The hashes in this list should only be changed if they come with a
# corresponding version bump in the affected objects.
object_data = {
    'Backup': '1.4-cae44fe34d5a870110ba93adebc1edca',
    'BackupImport': '1.4-cae44fe34d5a870110ba93adebc1edca',
    'BackupList': '1.0-7350483276ddb74960c8c39b69192eaa',
    'CGSnapshot': '1.0-78b91e76cb4c56e9cf5c9c41e208c05a',
    'CGSnapshotList': '1.0-e8c3f4078cd0ee23487b34d173eec776',
    'ConsistencyGroup': '1.2-3aeb6b25664057e8078bd6d45bf23e0a',
    'ConsistencyGroupList': '1.1-73916823b697dfa0c7f02508d87e0f28',
    'Service': '1.3-66c8e1683f58546c54551e9ff0a3b111',
    'ServiceList': '1.1-07d2be494d704784ad2af4d4c91e68e5',
    'Snapshot': '1.0-404c1a8b48a808aa0b7cc92cd3ec1e57',
    'SnapshotList': '1.0-58441afd20ddf9417b8879aa6de1ee6f',
    'Volume': '1.3-264388ec57bc4c3353c89f93bebf9482',
    'VolumeList': '1.1-8859f973dc02e9eb4582063a171bd0f1',
    'VolumeAttachment': '1.0-8fc9a9ac6f554fdf2a194d25dbf28a3b',
    'VolumeAttachmentList': '1.0-4ef79b3824e5d1717ebe0d0558ddff96',
    'VolumeType': '1.0-dd980cfd1eef2dcce941a981eb469fc8',
    'VolumeTypeList': '1.1-68a4549e98563caec82a2018638fa69c',
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
