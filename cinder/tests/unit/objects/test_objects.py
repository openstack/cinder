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
    'Backup': '1.5-3ab4b305bd43ec0cff6701fe2a849194',
    'BackupDeviceInfo': '1.0-74b3950676c690538f4bc6796bd0042e',
    'BackupImport': '1.5-3ab4b305bd43ec0cff6701fe2a849194',
    'BackupList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'CleanupRequest': '1.0-e7c688b893e1d5537ccf65cc3eb10a28',
    'Cluster': '1.1-e2c533eb8cdd8d229b6c45c6cf3a9e2c',
    'ClusterList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'CGSnapshot': '1.1-3212ac2b4c2811b7134fb9ba2c49ff74',
    'CGSnapshotList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'ConsistencyGroup': '1.4-7bf01a79b82516639fc03cd3ab6d9c01',
    'ConsistencyGroupList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'LogLevel': '1.0-7a8200b6b5063b33ec7b569dc6be66d2',
    'LogLevelList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'ManageableSnapshot': '1.0-5be933366eb17d12db0115c597158d0d',
    'ManageableSnapshotList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'ManageableVolume': '1.0-5fd0152237ec9dfb7b5c7095b8b09ffa',
    'ManageableVolumeList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'QualityOfServiceSpecs': '1.0-0b212e0a86ee99092229874e03207fe8',
    'QualityOfServiceSpecsList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'RequestSpec': '1.1-b0bd1a28d191d75648901fa853e8a733',
    'Service': '1.4-a6727ccda6d4043f5e38e75c7c518c7f',
    'ServiceList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'Snapshot': '1.5-ac1cdbd5b89588f6a8f44afdf6b8b201',
    'SnapshotList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'Volume': '1.6-7d3bc8577839d5725670d55e480fe95f',
    'VolumeList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'VolumeAttachment': '1.2-b68b357a1756582b706006ea9de40c9a',
    'VolumeAttachmentList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'VolumeProperties': '1.1-cadac86b2bdc11eb79d1dcea988ff9e8',
    'VolumeType': '1.3-a5d8c3473db9bc3bbcdbab9313acf4d1',
    'VolumeTypeList': '1.1-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'GroupType': '1.0-d4a7b272199d0b0d6fc3ceed58539d30',
    'GroupTypeList': '1.0-15ecf022a68ddbb8c2a6739cfc9f8f5e',
    'Group': '1.2-2ade6acf2e55687b980048fc3f51dad9',
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
                         "Some objects have changed; please make sure the "
                         "versions have been bumped and backporting "
                         "compatibility code has been added to "
                         "obj_make_compatible if necessary, and then update "
                         "their hashes in the object_data map in this test "
                         "module.  If we don't need to add backporting code "
                         "then it means we also don't need the version bump "
                         "and we just have to change the hash in this module.")

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
        init_kwargs = {objects.Snapshot: {'context': 'ctxt'},
                       objects.Backup: {'context': 'ctxt'},
                       objects.BackupImport: {'context': 'ctxt'}}
        checker = fixture.ObjectVersionChecker(
            base.CinderObjectRegistry.obj_classes())
        checker.test_compatibility_routines(init_args=init_args,
                                            init_kwargs=init_kwargs)
