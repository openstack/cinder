# Copyright 2014 IBM Corp.
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

"""
Handles all requests relating to volume replication.
"""
import functools

from oslo.config import cfg

from cinder.db import base
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder import policy
from cinder import volume as cinder_volume
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import utils as volume_utils

CONF = cfg.CONF

LOG = logging.getLogger(__name__)

PROMOTE_PROCEED_STATUS = ('active', 'active-stopped')
REENABLE_PROCEED_STATUS = ('inactive', 'active-stopped', 'error')


def wrap_check_policy(func):
    """Check policy corresponding to the wrapped methods prior to execution.

    This decorator requires the first 3 args of the wrapped function
    to be (self, context, relationship_id)
    """
    @functools.wraps(func)
    def wrapped(self, context, target_obj, *args, **kwargs):
        check_policy(context, func.__name__, target_obj)
        return func(self, context, target_obj, *args, **kwargs)
    return wrapped


def check_policy(context, action, target_obj=None):
    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }
    target.update(target_obj or {})
    _action = 'volume_extension:replication:%s' % action
    policy.enforce(context, _action, target)


class API(base.Base):
    """API for interacting with volume replication relationships."""

    def __init__(self, db_driver=None):
        super(API, self).__init__(db_driver)
        self.volume_rpcapi = volume_rpcapi.VolumeAPI()
        self.volume_api = cinder_volume.API()

    @wrap_check_policy
    def promote(self, context, vol):
        if vol['replication_status'] == 'disabled':
            msg = _("Replication is not enabled for volume")
            raise exception.ReplicationError(
                reason=msg,
                volume_id=vol['id'])
        if vol['replication_status'] not in PROMOTE_PROCEED_STATUS:
            msg = _("Replication status for volume must be active or "
                    "active-stopped, but current status "
                    "is: %s") % vol['replication_status']
            raise exception.ReplicationError(
                reason=msg,
                volume_id=vol['id'])

        if vol['status'] != 'available':
            msg = _("Volume status for volume must be available, but current "
                    "status is: %s") % vol['status']
            raise exception.ReplicationError(
                reason=msg,
                volume_id=vol['id'])
        volume_utils.notify_about_replication_usage(context,
                                                    vol,
                                                    'promote')
        self.volume_rpcapi.promote_replica(context, vol)

    @wrap_check_policy
    def reenable(self, context, vol):
        if vol['replication_status'] == 'disabled':
            msg = _("Replication is not enabled")
            raise exception.ReplicationError(
                reason=msg,
                volume_id=vol['id'])
        if vol['replication_status'] not in REENABLE_PROCEED_STATUS:
            msg = _("Replication status for volume must be inactive,"
                    " active-stopped, or error, but current status "
                    "is: %s") % vol['replication_status']
            raise exception.ReplicationError(
                reason=msg,
                volume_id=vol['id'])

        volume_utils.notify_about_replication_usage(context,
                                                    vol,
                                                    'sync')
        self.volume_rpcapi.reenable_replication(context, vol)
