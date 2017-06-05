# Copyright 2012 IBM Corp.
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


from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
from six.moves import http_client
import webob.exc

from cinder.api import common
from cinder.api import extensions
from cinder.api.openstack import wsgi
from cinder.backup import rpcapi as backup_rpcapi
from cinder.common import constants
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import utils
from cinder import volume
from cinder.volume import rpcapi as volume_rpcapi


CONF = cfg.CONF

LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('volume', 'services')


class ServiceController(wsgi.Controller):
    LOG_BINARIES = (constants.SCHEDULER_BINARY, constants.VOLUME_BINARY,
                    constants.BACKUP_BINARY, constants.API_BINARY)

    def __init__(self, ext_mgr=None):
        self.ext_mgr = ext_mgr
        super(ServiceController, self).__init__()
        self.volume_api = volume.API()
        self.rpc_apis = {
            constants.SCHEDULER_BINARY: scheduler_rpcapi.SchedulerAPI(),
            constants.VOLUME_BINARY: volume_rpcapi.VolumeAPI(),
            constants.BACKUP_BINARY: backup_rpcapi.BackupAPI(),
        }

    def index(self, req):
        """Return a list of all running services.

        Filter by host & service name.
        """
        context = req.environ['cinder.context']
        authorize(context, action='index')
        detailed = self.ext_mgr.is_loaded('os-extended-services')
        now = timeutils.utcnow(with_timezone=True)

        filters = {}

        if 'host' in req.GET:
            filters['host'] = req.GET['host']
        if 'binary' in req.GET:
            filters['binary'] = req.GET['binary']

        services = objects.ServiceList.get_all(context, filters)

        svcs = []
        for svc in services:
            updated_at = svc.updated_at
            delta = now - (svc.updated_at or svc.created_at)
            delta_sec = delta.total_seconds()
            if svc.modified_at:
                delta_mod = now - svc.modified_at
                if abs(delta_sec) >= abs(delta_mod.total_seconds()):
                    updated_at = svc.modified_at
            alive = abs(delta_sec) <= CONF.service_down_time
            art = "up" if alive else "down"
            active = 'enabled'
            if svc.disabled:
                active = 'disabled'
            if updated_at:
                updated_at = timeutils.normalize_time(updated_at)
            ret_fields = {'binary': svc.binary, 'host': svc.host,
                          'zone': svc.availability_zone,
                          'status': active, 'state': art,
                          'updated_at': updated_at}

            # On V3.7 we added cluster support
            if req.api_version_request.matches('3.7'):
                ret_fields['cluster'] = svc.cluster_name

            if detailed:
                ret_fields['disabled_reason'] = svc.disabled_reason
                if svc.binary == "cinder-volume":
                    ret_fields['replication_status'] = svc.replication_status
                    ret_fields['active_backend_id'] = svc.active_backend_id
                    ret_fields['frozen'] = svc.frozen
            svcs.append(ret_fields)
        return {'services': svcs}

    def _is_valid_as_reason(self, reason):
        if not reason:
            return False
        try:
            utils.check_string_length(reason, 'Disabled reason', min_length=1,
                                      max_length=255, allow_all_spaces=False)
        except exception.InvalidInput:
            return False

        return True

    def _volume_api_proxy(self, fun, *args):
        try:
            return fun(*args)
        except exception.ServiceNotFound as ex:
            raise exception.InvalidInput(ex.msg)

    def _freeze(self, context, req, body):
        cluster_name, host = common.get_cluster_host(req, body, '3.26')
        return self._volume_api_proxy(self.volume_api.freeze_host, context,
                                      host, cluster_name)

    def _thaw(self, context, req, body):
        cluster_name, host = common.get_cluster_host(req, body, '3.26')
        return self._volume_api_proxy(self.volume_api.thaw_host, context,
                                      host, cluster_name)

    def _failover(self, context, req, body, clustered):
        # We set version to None to always get the cluster name from the body,
        # to False when we don't want to get it, and '3.26' when we only want
        # it if the requested version is 3.26 or higher.
        version = '3.26' if clustered else False
        cluster_name, host = common.get_cluster_host(req, body, version)
        self._volume_api_proxy(self.volume_api.failover, context, host,
                               cluster_name, body.get('backend_id'))
        return webob.Response(status_int=http_client.ACCEPTED)

    def _log_params_binaries_services(self, context, body):
        """Get binaries and services referred by given log set/get request."""
        query_filters = {'is_up': True}

        binary = body.get('binary')
        if binary in ('*', None, ''):
            binaries = self.LOG_BINARIES
        elif binary == constants.API_BINARY:
            return [binary], []
        elif binary in self.LOG_BINARIES:
            binaries = [binary]
            query_filters['binary'] = binary
        else:
            raise exception.InvalidInput(reason=_('%s is not a valid binary.')
                                         % binary)

        server = body.get('server')
        if server:
            query_filters['host_or_cluster'] = server
        services = objects.ServiceList.get_all(context, filters=query_filters)

        return binaries, services

    def _set_log(self, context, body):
        """Set log levels of services dynamically."""
        prefix = body.get('prefix')
        level = body.get('level')
        # Validate log level
        utils.get_log_method(level)

        binaries, services = self._log_params_binaries_services(context, body)

        log_req = objects.LogLevel(context, prefix=prefix, level=level)

        if constants.API_BINARY in binaries:
            utils.set_log_levels(prefix, level)
        for service in services:
            self.rpc_apis[service.binary].set_log_levels(context,
                                                         service, log_req)

        return webob.Response(status_int=202)

    def _get_log(self, context, body):
        """Get current log levels for services."""
        prefix = body.get('prefix')
        binaries, services = self._log_params_binaries_services(context, body)

        result = []

        log_req = objects.LogLevel(context, prefix=prefix)

        if constants.API_BINARY in binaries:
            levels = utils.get_log_levels(prefix)
            result.append({'host': CONF.host,
                           'binary': constants.API_BINARY,
                           'levels': levels})
        for service in services:
            levels = self.rpc_apis[service.binary].get_log_levels(context,
                                                                  service,
                                                                  log_req)
            result.append({'host': service.host,
                           'binary': service.binary,
                           'levels': {l.prefix: l.level for l in levels}})

        return {'log_levels': result}

    def update(self, req, id, body):
        """Enable/Disable scheduling for a service.

        Includes Freeze/Thaw which sends call down to drivers
        and allows volume.manager for the specified host to
        disable the service rather than accessing the service
        directly in this API layer.
        """
        context = req.environ['cinder.context']
        authorize(context, action='update')

        support_dynamic_log = req.api_version_request.matches('3.32')

        ext_loaded = self.ext_mgr.is_loaded('os-extended-services')
        ret_val = {}
        if id == "enable":
            disabled = False
            status = "enabled"
            if ext_loaded:
                ret_val['disabled_reason'] = None
        elif (id == "disable" or
                (id == "disable-log-reason" and ext_loaded)):
            disabled = True
            status = "disabled"
        elif id == "freeze":
            return self._freeze(context, req, body)
        elif id == "thaw":
            return self._thaw(context, req, body)
        elif id == "failover_host":
            return self._failover(context, req, body, False)
        elif req.api_version_request.matches('3.26') and id == 'failover':
            return self._failover(context, req, body, True)
        elif support_dynamic_log and id == 'set-log':
            return self._set_log(context, body)
        elif support_dynamic_log and id == 'get-log':
            return self._get_log(context, body)
        else:
            raise exception.InvalidInput(reason=_("Unknown action"))

        host = common.get_cluster_host(req, body, False)[1]

        ret_val['disabled'] = disabled
        if id == "disable-log-reason" and ext_loaded:
            reason = body.get('disabled_reason')
            if not self._is_valid_as_reason(reason):
                msg = _('Disabled reason contains invalid characters '
                        'or is too long')
                raise webob.exc.HTTPBadRequest(explanation=msg)
            ret_val['disabled_reason'] = reason

        # NOTE(uni): deprecating service request key, binary takes precedence
        # Still keeping service key here for API compatibility sake.
        service = body.get('service', '')
        binary = body.get('binary', '')
        binary_key = binary or service
        if not binary_key:
            raise webob.exc.HTTPBadRequest()

        # Not found exception will be handled at the wsgi level
        svc = objects.Service.get_by_args(context, host, binary_key)

        svc.disabled = ret_val['disabled']
        if 'disabled_reason' in ret_val:
            svc.disabled_reason = ret_val['disabled_reason']
        svc.save()

        ret_val.update({'host': host, 'service': service,
                        'binary': binary, 'status': status})
        return ret_val


class Services(extensions.ExtensionDescriptor):
    """Services support."""

    name = "Services"
    alias = "os-services"
    updated = "2012-10-28T00:00:00-00:00"

    def get_resources(self):
        resources = []
        controller = ServiceController(self.ext_mgr)
        resource = extensions.ResourceExtension('os-services', controller)
        resources.append(resource)
        return resources
