#    Copyright 2015 Intel Corporation
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

from cinder import context
from cinder import exception
from cinder import objects
from cinder.tests.unit import objects as test_objects
from cinder.tests.unit.objects.test_consistencygroup import \
    fake_consistencygroup

fake_cgsnapshot = {
    'id': '1',
    'user_id': 'fake_user_id',
    'project_id': 'fake_project_id',
    'name': 'fake_name',
    'description': 'fake_description',
    'status': 'creating',
    'consistencygroup_id': 'fake_id',
}


class TestCGSnapshot(test_objects.BaseObjectsTestCase):
    def setUp(self):
        super(TestCGSnapshot, self).setUp()
        # NOTE (e0ne): base tests contains original RequestContext from
        # oslo_context. We change it to our RequestContext implementation
        # to have 'elevated' method
        self.user_id = 123
        self.project_id = 456
        self.context = context.RequestContext(self.user_id, self.project_id,
                                              is_admin=False)

    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], getattr(obj, field))

    @mock.patch('cinder.db.cgsnapshot_get',
                return_value=fake_cgsnapshot)
    def test_get_by_id(self, cgsnapshot_get):
        cgsnapshot = objects.CGSnapshot.get_by_id(self.context, 1)
        self._compare(self, fake_cgsnapshot, cgsnapshot)

    @mock.patch('cinder.db.cgsnapshot_create',
                return_value=fake_cgsnapshot)
    def test_create(self, cgsnapshot_create):
        fake_cgsnap = fake_cgsnapshot.copy()
        del fake_cgsnap['id']
        cgsnapshot = objects.CGSnapshot(context=self.context, **fake_cgsnap)
        cgsnapshot.create()
        self._compare(self, fake_cgsnapshot, cgsnapshot)

    def test_create_with_id_except_exception(self):
        cgsnapshot = objects.CGSnapshot(context=self.context, **{'id': 2})
        self.assertRaises(exception.ObjectActionError, cgsnapshot.create)

    @mock.patch('cinder.db.cgsnapshot_update')
    def test_save(self, cgsnapshot_update):
        cgsnapshot = objects.CGSnapshot._from_db_object(
            self.context, objects.CGSnapshot(), fake_cgsnapshot)
        cgsnapshot.status = 'active'
        cgsnapshot.save()
        cgsnapshot_update.assert_called_once_with(self.context, cgsnapshot.id,
                                                  {'status': 'active'})

    @mock.patch('cinder.db.consistencygroup_update',
                return_value=fake_consistencygroup)
    @mock.patch('cinder.db.cgsnapshot_update')
    def test_save_with_consistencygroup(self, cgsnapshot_update,
                                        cgsnapshot_cg_update):
        consistencygroup = objects.ConsistencyGroup._from_db_object(
            self.context, objects.ConsistencyGroup(), fake_consistencygroup)
        cgsnapshot = objects.CGSnapshot._from_db_object(
            self.context, objects.CGSnapshot(), fake_cgsnapshot)
        cgsnapshot.name = 'foobar'
        cgsnapshot.consistencygroup = consistencygroup
        self.assertEqual({'name': 'foobar',
                          'consistencygroup': consistencygroup},
                         cgsnapshot.obj_get_changes())
        self.assertRaises(exception.ObjectActionError, cgsnapshot.save)

    @mock.patch('cinder.db.cgsnapshot_destroy')
    def test_destroy(self, cgsnapshot_destroy):
        cgsnapshot = objects.CGSnapshot(context=self.context, id=1)
        cgsnapshot.destroy()
        self.assertTrue(cgsnapshot_destroy.called)
        admin_context = cgsnapshot_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)

    @mock.patch('cinder.objects.consistencygroup.ConsistencyGroup.get_by_id')
    @mock.patch('cinder.objects.snapshot.SnapshotList.get_all_for_cgsnapshot')
    def test_obj_load_attr(self, snapshotlist_get_for_cgs,
                           consistencygroup_get_by_id):
        cgsnapshot = objects.CGSnapshot._from_db_object(
            self.context, objects.CGSnapshot(), fake_cgsnapshot)
        # Test consistencygroup lazy-loaded field
        consistencygroup = objects.ConsistencyGroup(context=self.context, id=2)
        consistencygroup_get_by_id.return_value = consistencygroup
        self.assertEqual(consistencygroup, cgsnapshot.consistencygroup)
        consistencygroup_get_by_id.assert_called_once_with(
            self.context, cgsnapshot.consistencygroup_id)
        # Test snapshots lazy-loaded field
        snapshots_objs = [objects.Snapshot(context=self.context, id=i)
                          for i in [3, 4, 5]]
        snapshots = objects.SnapshotList(context=self.context,
                                         objects=snapshots_objs)
        snapshotlist_get_for_cgs.return_value = snapshots
        self.assertEqual(snapshots, cgsnapshot.snapshots)
        snapshotlist_get_for_cgs.assert_called_once_with(
            self.context, cgsnapshot.id)


class TestCGSnapshotList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.db.cgsnapshot_get_all',
                return_value=[fake_cgsnapshot])
    def test_get_all(self, cgsnapshot_get_all):
        cgsnapshots = objects.CGSnapshotList.get_all(self.context)
        self.assertEqual(1, len(cgsnapshots))
        TestCGSnapshot._compare(self, fake_cgsnapshot, cgsnapshots[0])

    @mock.patch('cinder.db.cgsnapshot_get_all_by_project',
                return_value=[fake_cgsnapshot])
    def test_get_all_by_project(self, cgsnapshot_get_all_by_project):
        cgsnapshots = objects.CGSnapshotList.get_all_by_project(
            self.context, self.project_id)
        self.assertEqual(1, len(cgsnapshots))
        TestCGSnapshot._compare(self, fake_cgsnapshot, cgsnapshots[0])

    @mock.patch('cinder.db.cgsnapshot_get_all_by_group',
                return_value=[fake_cgsnapshot])
    def test_get_all_by_group(self, cgsnapshot_get_all_by_group):
        cgsnapshots = objects.CGSnapshotList.get_all_by_group(
            self.context, self.project_id)
        self.assertEqual(1, len(cgsnapshots))
        TestCGSnapshot._compare(self, fake_cgsnapshot, cgsnapshots[0])
