# Copyright 2011 OpenStack LLC.
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

import cinder
from cinder.openstack.common import log as logging
import cinder.notifier.api
import cinder.notifier.log_notifier
import cinder.notifier.no_op_notifier
from cinder.notifier import list_notifier
from cinder import test


class NotifierListTestCase(test.TestCase):
    """Test case for notifications"""

    def setUp(self):
        super(NotifierListTestCase, self).setUp()
        list_notifier._reset_drivers()
        # Mock log to add one to exception_count when log.exception is called

        def mock_exception(cls, *args):
            self.exception_count += 1

        self.exception_count = 0
        list_notifier_log = logging.getLogger('cinder.notifier.list_notifier')
        self.stubs.Set(list_notifier_log, "exception", mock_exception)
        # Mock no_op notifier to add one to notify_count when called.

        def mock_notify(cls, *args):
            self.notify_count += 1

        self.notify_count = 0
        self.stubs.Set(cinder.notifier.no_op_notifier, 'notify', mock_notify)
        # Mock log_notifier to raise RuntimeError when called.

        def mock_notify2(cls, *args):
            raise RuntimeError("Bad notifier.")

        self.stubs.Set(cinder.notifier.log_notifier, 'notify', mock_notify2)

    def tearDown(self):
        list_notifier._reset_drivers()
        super(NotifierListTestCase, self).tearDown()

    def test_send_notifications_successfully(self):
        self.flags(notification_driver='cinder.notifier.list_notifier',
                   list_notifier_drivers=['cinder.notifier.no_op_notifier',
                                          'cinder.notifier.no_op_notifier'])
        cinder.notifier.api.notify('publisher_id', 'event_type',
                cinder.notifier.api.WARN, dict(a=3))
        self.assertEqual(self.notify_count, 2)
        self.assertEqual(self.exception_count, 0)

    def test_send_notifications_with_errors(self):

        self.flags(notification_driver='cinder.notifier.list_notifier',
                   list_notifier_drivers=['cinder.notifier.no_op_notifier',
                                          'cinder.notifier.log_notifier'])
        cinder.notifier.api.notify('publisher_id',
                'event_type', cinder.notifier.api.WARN, dict(a=3))
        self.assertEqual(self.notify_count, 1)
        self.assertEqual(self.exception_count, 1)

    def test_when_driver_fails_to_import(self):
        self.flags(notification_driver='cinder.notifier.list_notifier',
                   list_notifier_drivers=['cinder.notifier.no_op_notifier',
                                          'cinder.notifier.logo_notifier',
                                          'fdsjgsdfhjkhgsfkj'])
        cinder.notifier.api.notify('publisher_id',
                'event_type', cinder.notifier.api.WARN, dict(a=3))
        self.assertEqual(self.exception_count, 2)
        self.assertEqual(self.notify_count, 1)
