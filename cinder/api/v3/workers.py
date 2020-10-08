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
from http import HTTPStatus

from oslo_utils import strutils
from oslo_utils import timeutils

from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import workers
from cinder.api.v3.views import workers as workers_view
from cinder.api import validation
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import cleanable
from cinder.policies import workers as policy
from cinder.scheduler import rpcapi as sch_rpc
from cinder import utils


class WorkerController(wsgi.Controller):

    def __init__(self, *args, **kwargs):
        self.sch_api = sch_rpc.SchedulerAPI()

    @wsgi.Controller.api_version(mv.WORKERS_CLEANUP)
    @wsgi.response(HTTPStatus.ACCEPTED)
    @validation.schema(workers.cleanup)
    def cleanup(self, req, body=None):
        """Do the cleanup on resources from a specific service/host/node."""
        # Let the wsgi middleware convert NotAuthorized exceptions
        ctxt = req.environ['cinder.context']
        ctxt.authorize(policy.CLEAN_POLICY)
        body = body or {}

        for boolean in ('disabled', 'is_up'):
            if body.get(boolean) is not None:
                body[boolean] = strutils.bool_from_string(body[boolean])

        resource_type = body.get('resource_type')

        if resource_type:
            resource_type = resource_type.title()
            types = cleanable.CinderCleanableObject.cleanable_resource_types
            if resource_type not in types:
                valid_types = utils.build_or_str(types)
                msg = _('Resource type %(resource_type)s not valid,'
                        ' must be %(valid_types)s')
                msg = msg % {"resource_type": resource_type,
                             "valid_types": valid_types}
                raise exception.InvalidInput(reason=msg)
            body['resource_type'] = resource_type

        resource_id = body.get('resource_id')
        if resource_id:

            # If we have the resource type but we don't have where it is
            # located, we get it from the DB to limit the distribution of the
            # request by the scheduler, otherwise it will be distributed to all
            # the services.
            location_keys = {'service_id', 'cluster_name', 'host'}
            if not location_keys.intersection(body):
                workers = db.worker_get_all(ctxt, resource_id=resource_id,
                                            binary=body.get('binary'),
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
                body.update(service_id=worker.service_id,
                            resource_type=worker.resource_type)

        body['until'] = timeutils.utcnow()

        # NOTE(geguileo): If is_up is not specified in the request
        # CleanupRequest's default will be used (False)
        cleanup_request = objects.CleanupRequest(**body)
        cleaning, unavailable = self.sch_api.work_cleanup(ctxt,
                                                          cleanup_request)
        return {
            'cleaning': workers_view.ViewBuilder.service_list(cleaning),
            'unavailable': workers_view.ViewBuilder.service_list(unavailable),
        }


def create_resource():
    return wsgi.Resource(WorkerController())
