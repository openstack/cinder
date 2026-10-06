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

import sqlalchemy as sa

from cinder.db import api as db_api
from cinder.db import models
from cinder.tests.unit import test


class VolumeRelationshipsTestCase(test.TestCase):
    """Test cases for Volume ORM model relationshps."""

    def test_volume_dependent_models_list(self):
        """Make sure the volume dependent tables list is accurate."""
        # Addresses LP Bug #1542169

        mapper = sa.inspect(models.Volume)
        target_tables = set(mapper.tables)
        found_dependent_models = []
        for other_mapper in mapper.registry.mappers:
            if any(table in target_tables for table in other_mapper.tables):
                continue
            if any(
                fk.references(target_table)
                for table in other_mapper.tables
                for fk in table.foreign_keys
                for target_table in target_tables
            ):
                found_dependent_models.append(other_mapper.class_)

        self.assertEqual(len(found_dependent_models),
                         len(db_api.VOLUME_DEPENDENT_MODELS))
        for model in found_dependent_models:
            self.assertIn(model, db_api.VOLUME_DEPENDENT_MODELS)
