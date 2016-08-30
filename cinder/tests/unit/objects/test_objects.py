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
    'Cluster': '1.0-6f06e867c073e9d31722c53b0a9329b8',
    'ClusterList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'CGSnapshot': '1.0-3212ac2b4c2811b7134fb9ba2c49ff74',
    'CGSnapshotList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'ConsistencyGroup': '1.3-7bf01a79b82516639fc03cd3ab6d9c01',
    'ConsistencyGroupList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'QualityOfServiceSpecs': '1.0-0b212e0a86ee99092229874e03207fe8',
    'QualityOfServiceSpecsList': '1.0-1b54e51ad0fc1f3a8878f5010e7e16dc',
    'RequestSpec': '1.1-b0bd1a28d191d75648901fa853e8a733',
    'Service': '1.4-c7d011989d1718ca0496ccf640b42712',
    'ServiceList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'Snapshot': '1.1-d6a9d58f627bb2a5cf804b0dd7a12bc7',
    'SnapshotList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'Volume': '1.5-19919d8086d6a38ab9d3ab88139e70e0',
    'VolumeList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'VolumeAttachment': '1.0-b30dacf62b2030dd83d8a1603f1064ff',
    'VolumeAttachmentList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'VolumeProperties': '1.1-cadac86b2bdc11eb79d1dcea988ff9e8',
    'VolumeType': '1.2-02ecb0baac87528d041f4ddd95b95579',
    'VolumeTypeList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'GroupType': '1.0-d4a7b272199d0b0d6fc3ceed58539d30',
    'GroupTypeList': '1.0-1b54e51ad0fc1f3a8878f5010e7e16dc',
    'Group': '1.1-bd853b1d1ee05949d9ce4b33f80ac1a0',
    'GroupList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'GroupSnapshot': '1.0-9af3e994e889cbeae4427c3e351fa91d',
    'GroupSnapshotList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
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
                # NOTE(xyang): Skip the comparison of the colume name
                # group_type_id in table Group because group_type_id
                # is in the object Group but it is stored in a different
                # table in the database, not in the Group table.
                if (column.name in cls.fields and
                        (column.name != 'group_type_id' and name != 'Group')):
                    self.assertEqual(
                        column.nullable,
                        cls.fields[column.name].nullable,
                        'Column %(c)s in table %(t)s not match.'
                        % {'c': column.name,
                           't': name})

        classes = base.CinderObjectRegistry.obj_classes()
        for name, cls in classes.items():
            if issubclass(cls[0], base.CinderPersistentObject):
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
