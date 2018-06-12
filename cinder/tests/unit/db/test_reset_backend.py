# Copyright (c) 2018 Red Hat, Inc.
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

"""Tests for resetting active backend replication parameters."""

from cinder import db
from cinder import exception
from cinder.tests.unit import test_db_api
from cinder.tests.unit import utils


class ResetActiveBackendCase(test_db_api.BaseTest):
    """Unit tests for cinder.db.api.reset_active_backend."""

    def test_enabled_service(self):
        """Test that enabled services cannot be queried."""
        service_overrides = {'topic': 'cinder-volume'}
        service = utils.create_service(self.ctxt, values=service_overrides)
        self.assertRaises(exception.ServiceNotFound,
                          db.reset_active_backend,
                          self.ctxt, True, 'fake-backend-id',
                          service.host)

    def test_disabled_service(self):
        """Test that non-frozen services are rejected."""
        service_overrides = {'topic': 'cinder-volume',
                             'disabled': True}
        service = utils.create_service(self.ctxt, values=service_overrides)
        self.assertRaises(exception.ServiceUnavailable,
                          db.reset_active_backend,
                          self.ctxt, True, 'fake-backend-id',
                          service.host)

    def test_disabled_and_frozen_service(self):
        """Test that disabled and frozen services are updated correctly."""
        service_overrides = {'topic': 'cinder-volume',
                             'disabled': True,
                             'frozen': True,
                             'replication_status': 'failed-over',
                             'active_backend_id': 'seconary'}
        service = utils.create_service(self.ctxt, values=service_overrides)
        db.reset_active_backend(self.ctxt, True, 'fake-backend-id',
                                service.host)
        db_service = db.service_get(self.ctxt, service.id)

        self.assertFalse(db_service.disabled)
        self.assertEqual('', db_service.disabled_reason)
        self.assertIsNone(db_service.active_backend_id)
        self.assertEqual('enabled', db_service.replication_status)
