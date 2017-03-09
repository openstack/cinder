# Copyright (c) 2014 Pure Storage, Inc.
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

from oslo_log import log as logging

from cinder import context
from cinder import exception

LOG = logging.getLogger(__name__)


class VolumeDriverUtils(object):
    def __init__(self, namespace, db):
        self._data_namespace = namespace
        self._db = db

    @staticmethod
    def _get_context(ctxt):
        if not ctxt:
            return context.get_admin_context()
        return ctxt

    def get_driver_initiator_data(self, initiator, ctxt=None):
        try:
            return self._db.driver_initiator_data_get(
                self._get_context(ctxt),
                initiator,
                self._data_namespace
            )
        except exception.CinderException:
            LOG.exception("Failed to get driver initiator data for"
                          " initiator %(initiator)s and namespace"
                          " %(namespace)s",
                          {'initiator': initiator,
                           'namespace': self._data_namespace})
            raise

    def insert_driver_initiator_data(self, initiator, key, value, ctxt=None):
        """Update the initiator data at key with value.

        If the key has already been set to something return False, otherwise
        if saved successfully return True.
        """
        try:
            return self._db.driver_initiator_data_insert_by_key(
                self._get_context(ctxt),
                initiator,
                self._data_namespace,
                key,
                value
            )
        except exception.CinderException:
            LOG.exception("Failed to insert initiator data for"
                          " initiator %(initiator)s and backend"
                          " %(backend)s for key %(key)s.",
                          {'initiator': initiator,
                           'backend': self._data_namespace,
                           'key': key})
            raise
