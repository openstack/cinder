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
from cinder.common import sqlalchemyutils
from cinder import context
from cinder.db.sqlalchemy import api as db_api
from cinder.db.sqlalchemy import models
from cinder.tests.unit import fake_constants as fake
from cinder.tests.unit import test


class TestPaginateQuery(test.TestCase):
    def setUp(self):
        super(TestPaginateQuery, self).setUp()
        self.ctxt = context.RequestContext(fake.USER_ID, fake.PROJECT_ID,
                                           auth_token=True,
                                           is_admin=True)
        self.query = db_api._volume_get_query(self.ctxt)
        self.model = models.Volume

    def test_paginate_query_marker_null(self):
        marker_object = self.model()
        self.assertIsNone(marker_object.display_name)
        self.assertIsNone(marker_object.updated_at)

        marker_object.size = 1
        # There is no error raised here.
        sqlalchemyutils.paginate_query(self.query, self.model, 10,
                                       sort_keys=['display_name',
                                                  'updated_at',
                                                  'size'],
                                       marker=marker_object,
                                       sort_dirs=['desc', 'asc', 'desc'])
