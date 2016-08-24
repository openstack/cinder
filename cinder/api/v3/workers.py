# Copyright (c) 2016 Red Hat, Inc.
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

from oslo_utils import timeutils
from oslo_utils import uuidutils

from cinder.api.openstack import wsgi
from cinder.api.v3.views import workers as workers_view
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import cleanable
from cinder.scheduler import rpcapi as sch_rpc
from cinder import utils


class WorkerController(wsgi.Controller):
    allowed_clean_keys = {'service_id', 'cluster_name', 'host', 'binary',
                          'is_up', 'disabled', 'resource_id', 'resource_type',
                          'until'}

    policy_checker = wsgi.Controller.get_policy_checker('workers')

    def __init__(self, *args, **kwargs):
        self.sch_api = sch_rpc.SchedulerAPI()

    def _prepare_params(self, ctxt, params, allowed):
        if not allowed.issuperset(params):
            invalid_keys = set(params).difference(allowed)
            msg = _('Invalid filter keys: %s') % ', '.join(invalid_keys)
            raise exception.InvalidInput(reason=msg)

        if params.get('binary') not in (None, 'cinder-volume',
                                        'cinder-scheduler'):
            msg = _('binary must be empty or set to cinder-volume or '
                    'cinder-scheduler')
            raise exception.InvalidInput(reason=msg)

        for boolean in ('disabled', 'is_up'):
            if params.get(boolean) is not None:
                params[boolean] = utils.get_bool_param(boolean, params)

        resource_type = params.get('resource_type')

        if resource_type:
            resource_type = resource_type.title()
            types = cleanable.CinderCleanableObject.cleanable_resource_types
            if resource_type not in types:
                msg = (_('Resource type %s not valid, must be ') %
                       resource_type)
                msg = utils.build_or_str(types, msg + '%s.')
                raise exception.InvalidInput(reason=msg)
            params['resource_type'] = resource_type

        resource_id = params.get('resource_id')
        if resource_id:
            if not uuidutils.is_uuid_like(resource_id):
                msg = (_('Resource ID must be a UUID, and %s is not.') %
                       resource_id)
                raise exception.InvalidInput(reason=msg)

            # If we have the resource type but we don't have where it is
            # located, we get it from the DB to limit the distribution of the
            # request by the scheduler, otherwise it will be distributed to all
            # the services.
            location_keys = {'service_id', 'cluster_name', 'host'}
            if not location_keys.intersection(params):
                workers = db.worker_get_all(ctxt, resource_id=resource_id,
                                            binary=params.get('binary'),
                                            resource_type=resource_type)

                if len(workers) == 0:
                    msg = (_('There is no resource with UUID %s pending '
                             'cleanup.'), resource_id)
                    raise exception.InvalidInput(reason=msg)
                if len(workers) > 1:
                    msg = (_('There are multiple resources with UUID %s '
                             'pending cleanup.  Please be more specific.'),
                           resource_id)
                    raise exception.InvalidInput(reason=msg)

                worker = workers[0]
                params.update(service_id=worker.service_id,
                              resource_type=worker.resource_type)

        return params

    @wsgi.Controller.api_version('3.24')
    @wsgi.response(202)
    def cleanup(self, req, body=None):
        """Do the cleanup on resources from a specific service/host/node."""
        # Let the wsgi middleware convert NotAuthorized exceptions
        ctxt = self.policy_checker(req, 'cleanup')
        body = body or {}

        params = self._prepare_params(ctxt, body, self.allowed_clean_keys)
        params['until'] = timeutils.utcnow()

        # NOTE(geguileo): If is_up is not specified in the request
        # CleanupRequest's default will be used (False)
        cleanup_request = objects.CleanupRequest(**params)
        cleaning, unavailable = self.sch_api.work_cleanup(ctxt,
                                                          cleanup_request)
        return {
            'cleaning': workers_view.ViewBuilder.service_list(cleaning),
            'unavailable': workers_view.ViewBuilder.service_list(unavailable),
        }


def create_resource():
    return wsgi.Resource(WorkerController())
