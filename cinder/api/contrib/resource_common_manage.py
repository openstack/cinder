#  Copyright (c) 2016 Stratoscale, Ltd.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import oslo_messaging as messaging

from cinder.api import common
from cinder.api import microversions as mv
from cinder import exception
from cinder.i18n import _


def get_manageable_resources(req, is_detail, function_get_manageable,
                             view_builder):
    context = req.environ['cinder.context']
    params = req.params.copy()
    cluster_name, host = common.get_cluster_host(
        req, params, mv.MANAGE_EXISTING_CLUSTER)
    marker, limit, offset = common.get_pagination_params(params)
    sort_keys, sort_dirs = common.get_sort_params(params,
                                                  default_key='reference')

    # These parameters are generally validated at the DB layer, but in this
    # case sorting is not done by the DB
    valid_sort_keys = ('reference', 'size')
    invalid_keys = [key for key in sort_keys if key not in valid_sort_keys]
    if invalid_keys:
        msg = _("Invalid sort keys passed: %s") % ', '.join(invalid_keys)
        raise exception.InvalidParameterValue(err=msg)
    valid_sort_dirs = ('asc', 'desc')
    invalid_dirs = [d for d in sort_dirs if d not in valid_sort_dirs]
    if invalid_dirs:
        msg = _("Invalid sort dirs passed: %s") % ', '.join(invalid_dirs)
        raise exception.InvalidParameterValue(err=msg)

    try:
        resources = function_get_manageable(context, host, cluster_name,
                                            marker=marker, limit=limit,
                                            offset=offset, sort_keys=sort_keys,
                                            sort_dirs=sort_dirs)
    except messaging.RemoteError as err:
        if err.exc_type == "InvalidInput":
            raise exception.InvalidInput(err.value)
        raise

    resource_count = len(resources)

    if is_detail:
        resources = view_builder.detail_list(req, resources, resource_count)
    else:
        resources = view_builder.summary_list(req, resources, resource_count)
    return resources
