# Copyright 2020 Red Hat, Inc.
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

"""Tests for code that makes assumptions about ORM relationships."""

from sqlalchemy_utils import functions as saf

from cinder.db.sqlalchemy import api as db_api
from cinder.db.sqlalchemy import models
from cinder.tests.unit import test


class VolumeRelationshipsTestCase(test.TestCase):
    """Test cases for Volume ORM model relationshps."""

    def test_volume_dependent_models_list(self):
        """Make sure the volume dependent tables list is accurate."""
        # Addresses LP Bug #1542169

        volume_declarative_base = saf.get_declarative_base(models.Volume)
        volume_fks = saf.get_referencing_foreign_keys(models.Volume)

        dependent_tables = []
        for table, fks in saf.group_foreign_keys(volume_fks):
            dependent_tables.append(table)

        found_dependent_models = []
        for table in dependent_tables:
            found_dependent_models.append(saf.get_class_by_table(
                volume_declarative_base, table))

        self.assertEqual(len(found_dependent_models),
                         len(db_api.VOLUME_DEPENDENT_MODELS))
        for model in found_dependent_models:
            self.assertIn(model, db_api.VOLUME_DEPENDENT_MODELS)
