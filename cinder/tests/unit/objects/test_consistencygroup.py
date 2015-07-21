# Copyright 2015 Yahoo Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

from cinder import context
from cinder import exception
from cinder import objects
from cinder.tests.unit import objects as test_objects

fake_consistencygroup = {
    'id': '1',
    'user_id': 'fake_user_id',
    'project_id': 'fake_project_id',
    'host': 'fake_host',
    'availability_zone': 'fake_az',
    'name': 'fake_name',
    'description': 'fake_description',
    'volume_type_id': 'fake_volume_type_id',
    'status': 'creating',
    'cgsnapshot_id': 'fake_id',
    'source_cgid': None,
}


class TestConsistencyGroup(test_objects.BaseObjectsTestCase):
    def setUp(self):
        super(TestConsistencyGroup, self).setUp()
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

    @mock.patch('cinder.db.consistencygroup_get',
                return_value=fake_consistencygroup)
    def test_get_by_id(self, consistencygroup_get):
        consistencygroup = objects.ConsistencyGroup.get_by_id(self.context, 1)
        self._compare(self, fake_consistencygroup, consistencygroup)

    @mock.patch('cinder.db.sqlalchemy.api.model_query')
    def test_get_by_id_no_existing_id(self, model_query):
        query = mock.Mock()
        filter_by = mock.Mock()
        filter_by.first.return_value = None
        query.filter_by.return_value = filter_by
        model_query.return_value = query
        self.assertRaises(exception.ConsistencyGroupNotFound,
                          objects.ConsistencyGroup.get_by_id, self.context,
                          123)

    @mock.patch('cinder.db.consistencygroup_create',
                return_value=fake_consistencygroup)
    def test_create(self, consistencygroup_create):
        fake_cg = fake_consistencygroup.copy()
        del fake_cg['id']
        consistencygroup = objects.ConsistencyGroup(context=self.context,
                                                    **fake_cg)
        consistencygroup.create()
        self._compare(self, fake_consistencygroup, consistencygroup)

    def test_create_with_id_except_exception(self, ):
        consistencygroup = objects.ConsistencyGroup(context=self.context,
                                                    **{'id': 1})
        self.assertRaises(exception.ObjectActionError, consistencygroup.create)

    @mock.patch('cinder.db.consistencygroup_update')
    def test_save(self, consistencygroup_update):
        consistencygroup = objects.ConsistencyGroup._from_db_object(
            self.context, objects.ConsistencyGroup(), fake_consistencygroup)
        consistencygroup.status = 'active'
        consistencygroup.save()
        consistencygroup_update.assert_called_once_with(self.context,
                                                        consistencygroup.id,
                                                        {'status': 'active'})

    @mock.patch('cinder.db.consistencygroup_destroy')
    def test_destroy(self, consistencygroup_destroy):
        consistencygroup = objects.ConsistencyGroup(context=self.context,
                                                    id='1')
        consistencygroup.destroy()
        self.assertTrue(consistencygroup_destroy.called)
        admin_context = consistencygroup_destroy.call_args[0][0]
        self.assertTrue(admin_context.is_admin)


class TestConsistencyGroupList(test_objects.BaseObjectsTestCase):
    @mock.patch('cinder.db.consistencygroup_get_all',
                return_value=[fake_consistencygroup])
    def test_get_all(self, consistencygroup_get_all):
        consistencygroups = objects.ConsistencyGroupList.get_all(self.context)
        self.assertEqual(1, len(consistencygroups))
        TestConsistencyGroup._compare(self, fake_consistencygroup,
                                      consistencygroups[0])

    @mock.patch('cinder.db.consistencygroup_get_all_by_project',
                return_value=[fake_consistencygroup])
    def test_get_all_by_project(self, consistencygroup_get_all_by_project):
        consistencygroups = objects.ConsistencyGroupList.get_all_by_project(
            self.context, self.project_id)
        self.assertEqual(1, len(consistencygroups))
        TestConsistencyGroup._compare(self, fake_consistencygroup,
                                      consistencygroups[0])
