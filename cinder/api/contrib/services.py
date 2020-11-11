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
from http import HTTPStatus

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
import webob.exc

from cinder.api import common
from cinder.api import extensions
from cinder.api import microversions as mv
from cinder.api.openstack import wsgi
from cinder.api.schemas import services as os_services
from cinder.api import validation
from cinder.backup import rpcapi as backup_rpcapi
from cinder.common import constants
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.policies import services as policy
from cinder.scheduler import rpcapi as scheduler_rpcapi
from cinder import utils
from cinder import volume
from cinder.volume import rpcapi as volume_rpcapi
from cinder.volume import volume_utils


CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class ServiceController(wsgi.Controller):
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
        context.authorize(policy.GET_ALL_POLICY)
        detailed = self.ext_mgr.is_loaded('os-extended-services')
        now = timeutils.utcnow(with_timezone=True)

        filters = {}

        if 'host' in req.GET:
            filters['host'] = req.GET['host']
        if 'binary' in req.GET:
            filters['binary'] = req.GET['binary']

        services = objects.ServiceList.get_all(context, filters)
        # Get backend state from scheduler
        if req.api_version_request.matches(mv.BACKEND_STATE_REPORT):
            backend_state_map = {}
            scheduler_api = self.rpc_apis[constants.SCHEDULER_BINARY]
            pools = scheduler_api.get_pools(context)
            for pool in pools:
                backend_name = volume_utils.extract_host(pool.get("name"))
                back_state = pool.get('capabilities', {}).get('backend_state',
                                                              'up')
                backend_state_map[backend_name] = back_state

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

            if (req.api_version_request.matches(mv.BACKEND_STATE_REPORT) and
                    svc.binary == constants.VOLUME_BINARY):
                ret_fields['backend_state'] = backend_state_map.get(svc.host)

            # On CLUSTER_SUPPORT we added cluster support
            if req.api_version_request.matches(mv.CLUSTER_SUPPORT):
                ret_fields['cluster'] = svc.cluster_name

            if detailed:
                ret_fields['disabled_reason'] = svc.disabled_reason
                if svc.binary == constants.VOLUME_BINARY:
                    ret_fields['replication_status'] = svc.replication_status
                    ret_fields['active_backend_id'] = svc.active_backend_id
                    ret_fields['frozen'] = svc.frozen
            svcs.append(ret_fields)
        return {'services': svcs}

    def _volume_api_proxy(self, fun, *args):
        try:
            return fun(*args)
        except exception.ServiceNotFound as ex:
            raise exception.InvalidInput(ex.msg)

    @validation.schema(os_services.freeze_and_thaw)
    def _freeze(self, req, context, body):
        cluster_name, host = common.get_cluster_host(
            req, body, mv.REPLICATION_CLUSTER)
        return self._volume_api_proxy(self.volume_api.freeze_host, context,
                                      host, cluster_name)

    @validation.schema(os_services.freeze_and_thaw)
    def _thaw(self, req, context, body):
        cluster_name, host = common.get_cluster_host(
            req, body, mv.REPLICATION_CLUSTER)
        return self._volume_api_proxy(self.volume_api.thaw_host, context,
                                      host, cluster_name)

    @validation.schema(os_services.failover_host)
    def _failover(self, req, context, clustered, body):
        # We set version to None to always get the cluster name from the body,
        # to False when we don't want to get it, and REPLICATION_CLUSTER  when
        # we only want it if the requested version is REPLICATION_CLUSTER  or
        # higher.
        version = mv.REPLICATION_CLUSTER if clustered else False
        cluster_name, host = common.get_cluster_host(req, body, version)
        self._volume_api_proxy(self.volume_api.failover, context, host,
                               cluster_name, body.get('backend_id'))
        return webob.Response(status_int=HTTPStatus.ACCEPTED)

    def _log_params_binaries_services(self, context, body):
        """Get binaries and services referred by given log set/get request."""
        query_filters = {'is_up': True}
        binary = body.get('binary')
        binaries = []
        if binary in ('*', None, ''):
            binaries = constants.LOG_BINARIES
        elif binary == constants.API_BINARY:
            return [binary], []
        elif binary in constants.LOG_BINARIES:
            binaries = [binary]
            query_filters['binary'] = binary

        server = body.get('server')
        if server:
            query_filters['host_or_cluster'] = server
        services = objects.ServiceList.get_all(context, filters=query_filters)

        return binaries, services

    @validation.schema(os_services.set_log)
    def _set_log(self, req, context, body):
        """Set log levels of services dynamically."""
        prefix = body.get('prefix')
        level = body.get('level')

        binaries, services = self._log_params_binaries_services(context, body)

        log_req = objects.LogLevel(context, prefix=prefix, level=level)

        if constants.API_BINARY in binaries:
            utils.set_log_levels(prefix, level)
        for service in services:
            self.rpc_apis[service.binary].set_log_levels(context,
                                                         service, log_req)

        return webob.Response(status_int=HTTPStatus.ACCEPTED)

    @validation.schema(os_services.get_log)
    def _get_log(self, req, context, body):
        """Get current log levels for services."""
        prefix = body.get('prefix')
        binaries, services = self._log_params_binaries_services(context, body)

        result = []

        log_req = objects.LogLevel(context, prefix=prefix)

        # Avoid showing constants if 'server' is set.
        server_filter = body.get('server')
        if not server_filter or server_filter == CONF.host:
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
                           'levels': {le.prefix: le.level for le in levels}})

        return {'log_levels': result}

    @validation.schema(os_services.disable_log_reason)
    def _disabled_log_reason(self, req, body):
        reason = body.get('disabled_reason')
        disabled = True
        status = "disabled"
        return reason, disabled, status

    @validation.schema(os_services.enable_and_disable)
    def _enable(self, req, body):
        disabled = False
        status = "enabled"
        return disabled, status

    @validation.schema(os_services.enable_and_disable)
    def _disable(self, req, body):
        disabled = True
        status = "disabled"
        return disabled, status

    def update(self, req, id, body):
        """Enable/Disable scheduling for a service.

        Includes Freeze/Thaw which sends call down to drivers
        and allows volume.manager for the specified host to
        disable the service rather than accessing the service
        directly in this API layer.
        """
        context = req.environ['cinder.context']
        context.authorize(policy.UPDATE_POLICY)

        support_dynamic_log = req.api_version_request.matches(mv.LOG_LEVEL)
        ext_loaded = self.ext_mgr.is_loaded('os-extended-services')
        ret_val = {}
        if id == "enable":
            disabled, status = self._enable(req, body=body)
        elif id == "disable":
            disabled, status = self._disable(req, body=body)
        elif id == "disable-log-reason" and ext_loaded:
            disabled_reason, disabled, status = (
                self._disabled_log_reason(req, body=body))
            ret_val['disabled_reason'] = disabled_reason
        elif id == "freeze":
            return self._freeze(req, context, body=body)
        elif id == "thaw":
            return self._thaw(req, context, body=body)
        elif id == "failover_host":
            return self._failover(req, context, False, body=body)
        elif (req.api_version_request.matches(mv.REPLICATION_CLUSTER) and
              id == 'failover'):
            return self._failover(req, context, True, body=body)
        elif support_dynamic_log and id == 'set-log':
            return self._set_log(req, context, body=body)
        elif support_dynamic_log and id == 'get-log':
            return self._get_log(req, context, body=body)
        else:
            raise exception.InvalidInput(reason=_("Unknown action"))

        host = common.get_cluster_host(req, body, False)[1]
        ret_val['disabled'] = disabled

        # NOTE(uni): deprecating service request key, binary takes precedence
        # Still keeping service key here for API compatibility sake.
        service = body.get('service', '')
        binary = body.get('binary', '')
        binary_key = binary or service

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
