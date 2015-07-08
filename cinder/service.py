# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

"""Generic Node base class for all workers that run on hosts."""


import inspect
import os
import random

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_service import loopingcall
from oslo_service import service
from oslo_utils import importutils
import osprofiler.notifier
from osprofiler import profiler
import osprofiler.web

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import objects
from cinder.objects import base as objects_base
from cinder import rpc
from cinder import version
from cinder.wsgi import common as wsgi_common
from cinder.wsgi import eventlet_server as wsgi

LOG = logging.getLogger(__name__)

service_opts = [
    cfg.IntOpt('report_interval',
               default=10,
               help='Interval, in seconds, between nodes reporting state '
                    'to datastore'),
    cfg.IntOpt('periodic_interval',
               default=60,
               help='Interval, in seconds, between running periodic tasks'),
    cfg.IntOpt('periodic_fuzzy_delay',
               default=60,
               help='Range, in seconds, to randomly delay when starting the'
                    ' periodic task scheduler to reduce stampeding.'
                    ' (Disable by setting to 0)'),
    cfg.StrOpt('osapi_volume_listen',
               default="0.0.0.0",
               help='IP address on which OpenStack Volume API listens'),
    cfg.IntOpt('osapi_volume_listen_port',
               default=8776,
               min=1, max=65535,
               help='Port on which OpenStack Volume API listens'),
    cfg.IntOpt('osapi_volume_workers',
               help='Number of workers for OpenStack Volume API service. '
                    'The default is equal to the number of CPUs available.'), ]

profiler_opts = [
    cfg.BoolOpt("profiler_enabled", default=False,
                help=_('If False fully disable profiling feature.')),
    cfg.BoolOpt("trace_sqlalchemy", default=False,
                help=_("If False doesn't trace SQL requests."))
]

CONF = cfg.CONF
CONF.register_opts(service_opts)
CONF.register_opts(profiler_opts, group="profiler")


def setup_profiler(binary, host):
    if CONF.profiler.profiler_enabled:
        _notifier = osprofiler.notifier.create(
            "Messaging", messaging, context.get_admin_context().to_dict(),
            rpc.TRANSPORT, "cinder", binary, host)
        osprofiler.notifier.set(_notifier)
        LOG.warning(
            _LW("OSProfiler is enabled.\nIt means that person who knows "
                "any of hmac_keys that are specified in "
                "/etc/cinder/api-paste.ini can trace his requests. \n"
                "In real life only operator can read this file so there "
                "is no security issue. Note that even if person can "
                "trigger profiler, only admin user can retrieve trace "
                "information.\n"
                "To disable OSprofiler set in cinder.conf:\n"
                "[profiler]\nenabled=false"))
    else:
        osprofiler.web.disable()


class Service(service.Service):
    """Service object for binaries running on hosts.

    A service takes a manager and enables rpc by listening to queues based
    on topic. It also periodically runs tasks on the manager and reports
    it state to the database services table.
    """

    def __init__(self, host, binary, topic, manager, report_interval=None,
                 periodic_interval=None, periodic_fuzzy_delay=None,
                 service_name=None, *args, **kwargs):
        super(Service, self).__init__()

        if not rpc.initialized():
            rpc.init(CONF)

        self.host = host
        self.binary = binary
        self.topic = topic
        self.manager_class_name = manager
        manager_class = importutils.import_class(self.manager_class_name)
        manager_class = profiler.trace_cls("rpc")(manager_class)

        self.manager = manager_class(host=self.host,
                                     service_name=service_name,
                                     *args, **kwargs)
        self.report_interval = report_interval
        self.periodic_interval = periodic_interval
        self.periodic_fuzzy_delay = periodic_fuzzy_delay
        self.basic_config_check()
        self.saved_args, self.saved_kwargs = args, kwargs
        self.timers = []

        setup_profiler(binary, host)
        self.rpcserver = None

    def start(self):
        version_string = version.version_string()
        LOG.info(_LI('Starting %(topic)s node (version %(version_string)s)'),
                 {'topic': self.topic, 'version_string': version_string})
        self.model_disconnected = False
        self.manager.init_host()
        ctxt = context.get_admin_context()
        try:
            service_ref = objects.Service.get_by_args(
                ctxt, self.host, self.binary)
            self.service_id = service_ref.id
        except exception.NotFound:
            self._create_service_ref(ctxt)

        LOG.debug("Creating RPC server for service %s", self.topic)

        target = messaging.Target(topic=self.topic, server=self.host)
        endpoints = [self.manager]
        endpoints.extend(self.manager.additional_endpoints)
        serializer = objects_base.CinderObjectSerializer()
        self.rpcserver = rpc.get_server(target, endpoints, serializer)
        self.rpcserver.start()

        self.manager.init_host_with_rpc()

        if self.report_interval:
            pulse = loopingcall.FixedIntervalLoopingCall(
                self.report_state)
            pulse.start(interval=self.report_interval,
                        initial_delay=self.report_interval)
            self.timers.append(pulse)

        if self.periodic_interval:
            if self.periodic_fuzzy_delay:
                initial_delay = random.randint(0, self.periodic_fuzzy_delay)
            else:
                initial_delay = None

            periodic = loopingcall.FixedIntervalLoopingCall(
                self.periodic_tasks)
            periodic.start(interval=self.periodic_interval,
                           initial_delay=initial_delay)
            self.timers.append(periodic)

    def basic_config_check(self):
        """Perform basic config checks before starting service."""
        # Make sure report interval is less than service down time
        if self.report_interval:
            if CONF.service_down_time <= self.report_interval:
                new_down_time = int(self.report_interval * 2.5)
                LOG.warning(
                    _LW("Report interval must be less than service down "
                        "time. Current config service_down_time: "
                        "%(service_down_time)s, report_interval for this: "
                        "service is: %(report_interval)s. Setting global "
                        "service_down_time to: %(new_down_time)s"),
                    {'service_down_time': CONF.service_down_time,
                     'report_interval': self.report_interval,
                     'new_down_time': new_down_time})
                CONF.set_override('service_down_time', new_down_time)

    def _create_service_ref(self, context):
        zone = CONF.storage_availability_zone
        kwargs = {'host': self.host,
                  'binary': self.binary,
                  'topic': self.topic,
                  'report_count': 0,
                  'availability_zone': zone}
        service_ref = objects.Service(context=context, **kwargs)
        service_ref.create()
        self.service_id = service_ref.id

    def __getattr__(self, key):
        manager = self.__dict__.get('manager', None)
        return getattr(manager, key)

    @classmethod
    def create(cls, host=None, binary=None, topic=None, manager=None,
               report_interval=None, periodic_interval=None,
               periodic_fuzzy_delay=None, service_name=None):
        """Instantiates class and passes back application object.

        :param host: defaults to CONF.host
        :param binary: defaults to basename of executable
        :param topic: defaults to bin_name - 'cinder-' part
        :param manager: defaults to CONF.<topic>_manager
        :param report_interval: defaults to CONF.report_interval
        :param periodic_interval: defaults to CONF.periodic_interval
        :param periodic_fuzzy_delay: defaults to CONF.periodic_fuzzy_delay

        """
        if not host:
            host = CONF.host
        if not binary:
            binary = os.path.basename(inspect.stack()[-1][1])
        if not topic:
            topic = binary
        if not manager:
            subtopic = topic.rpartition('cinder-')[2]
            manager = CONF.get('%s_manager' % subtopic, None)
        if report_interval is None:
            report_interval = CONF.report_interval
        if periodic_interval is None:
            periodic_interval = CONF.periodic_interval
        if periodic_fuzzy_delay is None:
            periodic_fuzzy_delay = CONF.periodic_fuzzy_delay
        service_obj = cls(host, binary, topic, manager,
                          report_interval=report_interval,
                          periodic_interval=periodic_interval,
                          periodic_fuzzy_delay=periodic_fuzzy_delay,
                          service_name=service_name)

        return service_obj

    def kill(self):
        """Destroy the service object in the datastore."""
        self.stop()
        try:
            service_ref = objects.Service.get_by_id(
                context.get_admin_context(), self.service_id)
            service_ref.destroy()
        except exception.NotFound:
            LOG.warning(_LW('Service killed that has no database entry'))

    def stop(self):
        # Try to shut the connection down, but if we get any sort of
        # errors, go ahead and ignore them.. as we're shutting down anyway
        try:
            self.rpcserver.stop()
        except Exception:
            pass
        for x in self.timers:
            try:
                x.stop()
            except Exception:
                pass
        self.timers = []
        super(Service, self).stop()

    def wait(self):
        for x in self.timers:
            try:
                x.wait()
            except Exception:
                pass
        if self.rpcserver:
            self.rpcserver.wait()

    def periodic_tasks(self, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        ctxt = context.get_admin_context()
        self.manager.periodic_tasks(ctxt, raise_on_error=raise_on_error)

    def report_state(self):
        """Update the state of this service in the datastore."""
        if not self.manager.is_working():
            # NOTE(dulek): If manager reports a problem we're not sending
            # heartbeats - to indicate that service is actually down.
            LOG.error(_LE('Manager for service %(binary)s %(host)s is '
                          'reporting problems, not sending heartbeat. '
                          'Service will appear "down".'),
                      {'binary': self.binary,
                       'host': self.host})
            return

        ctxt = context.get_admin_context()
        zone = CONF.storage_availability_zone
        try:
            try:
                service_ref = objects.Service.get_by_id(ctxt, self.service_id)
            except exception.NotFound:
                LOG.debug('The service database object disappeared, '
                          'recreating it.')
                self._create_service_ref(ctxt)
                service_ref = objects.Service.get_by_id(ctxt, self.service_id)

            service_ref.report_count += 1
            if zone != service_ref.availability_zone:
                service_ref.availability_zone = zone

            service_ref.save()

            # TODO(termie): make this pattern be more elegant.
            if getattr(self, 'model_disconnected', False):
                self.model_disconnected = False
                LOG.error(_LE('Recovered model server connection!'))

        except db_exc.DBConnectionError:
            if not getattr(self, 'model_disconnected', False):
                self.model_disconnected = True
                LOG.exception(_LE('model server went away'))

        # NOTE(jsbryant) Other DB errors can happen in HA configurations.
        # such errors shouldn't kill this thread, so we handle them here.
        except db_exc.DBError:
            if not getattr(self, 'model_disconnected', False):
                self.model_disconnected = True
                LOG.exception(_LE('DBError encountered: '))

        except Exception:
            if not getattr(self, 'model_disconnected', False):
                self.model_disconnected = True
                LOG.exception(_LE('Exception encountered: '))


class WSGIService(service.ServiceBase):
    """Provides ability to launch API from a 'paste' configuration."""

    def __init__(self, name, loader=None):
        """Initialize, but do not start the WSGI server.

        :param name: The name of the WSGI server given to the loader.
        :param loader: Loads the WSGI application using the given name.
        :returns: None

        """
        self.name = name
        self.manager = self._get_manager()
        self.loader = loader or wsgi_common.Loader()
        self.app = self.loader.load_app(name)
        self.host = getattr(CONF, '%s_listen' % name, "0.0.0.0")
        self.port = getattr(CONF, '%s_listen_port' % name, 0)
        self.workers = (getattr(CONF, '%s_workers' % name, None) or
                        processutils.get_worker_count())
        if self.workers and self.workers < 1:
            worker_name = '%s_workers' % name
            msg = (_("%(worker_name)s value of %(workers)d is invalid, "
                     "must be greater than 0.") %
                   {'worker_name': worker_name,
                    'workers': self.workers})
            raise exception.InvalidInput(msg)
        setup_profiler(name, self.host)

        self.server = wsgi.Server(name,
                                  self.app,
                                  host=self.host,
                                  port=self.port)

    def _get_manager(self):
        """Initialize a Manager object appropriate for this service.

        Use the service name to look up a Manager subclass from the
        configuration and initialize an instance. If no class name
        is configured, just return None.

        :returns: a Manager instance, or None.

        """
        fl = '%s_manager' % self.name
        if fl not in CONF:
            return None

        manager_class_name = CONF.get(fl, None)
        if not manager_class_name:
            return None

        manager_class = importutils.import_class(manager_class_name)
        return manager_class()

    def start(self):
        """Start serving this service using loaded configuration.

        Also, retrieve updated port number in case '0' was passed in, which
        indicates a random port should be used.

        :returns: None

        """
        if self.manager:
            self.manager.init_host()
        self.server.start()
        self.port = self.server.port

    def stop(self):
        """Stop serving this API.

        :returns: None

        """
        self.server.stop()

    def wait(self):
        """Wait for the service to stop serving this API.

        :returns: None

        """
        self.server.wait()

    def reset(self):
        """Reset server greenpool size to default.

        :returns: None

        """
        self.server.reset()


def process_launcher():
    return service.ProcessLauncher(CONF)


# NOTE(vish): the global launcher is to maintain the existing
#             functionality of calling service.serve +
#             service.wait
_launcher = None


def serve(server, workers=None):
    global _launcher
    if _launcher:
        raise RuntimeError(_('serve() can only be called once'))

    _launcher = service.launch(CONF, server, workers=workers)


def wait():
    LOG.debug('Full set of CONF:')
    for flag in CONF:
        flag_get = CONF.get(flag, None)
        # hide flag contents from log if contains a password
        # should use secret flag when switch over to openstack-common
        if ("_password" in flag or "_key" in flag or
                (flag == "sql_connection" and
                    ("mysql:" in flag_get or "postgresql:" in flag_get))):
            LOG.debug('%s : FLAG SET ', flag)
        else:
            LOG.debug('%(flag)s : %(flag_get)s',
                      {'flag': flag, 'flag_get': flag_get})
    try:
        _launcher.wait()
    except KeyboardInterrupt:
        _launcher.stop()
    rpc.cleanup()


class Launcher(object):
    def __init__(self):
        self.launch_service = serve
        self.wait = wait


def get_launcher():
    # Note(lpetrut): ProcessLauncher uses green pipes which fail on Windows
    # due to missing support of non-blocking I/O pipes. For this reason, the
    # service must be spawned differently on Windows, using the ServiceLauncher
    # class instead.
    if os.name == 'nt':
        return Launcher()
    else:
        return process_launcher()
