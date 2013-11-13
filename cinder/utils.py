# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""Utilities and helper functions."""


import contextlib
import datetime
import functools
import hashlib
import inspect
import os
import pyclbr
import random
import re
import shutil
import sys
import tempfile
import time
from xml.dom import minidom
from xml.parsers import expat
from xml import sax
from xml.sax import expatreader
from xml.sax import saxutils

from eventlet import event
from eventlet import greenthread
from eventlet import pools
from oslo.config import cfg
import paramiko

from cinder.brick.initiator import connector
from cinder import exception
from cinder.openstack.common import excutils
from cinder.openstack.common import gettextutils
from cinder.openstack.common import importutils
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder.openstack.common import timeutils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)
ISO_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
PERFECT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"

synchronized = lockutils.synchronized_with_prefix('cinder-')


def find_config(config_path):
    """Find a configuration file using the given hint.

    :param config_path: Full or relative path to the config.
    :returns: Full path of the config, if it exists.
    :raises: `cinder.exception.ConfigNotFound`

    """
    possible_locations = [
        config_path,
        os.path.join(CONF.state_path, "etc", "cinder", config_path),
        os.path.join(CONF.state_path, "etc", config_path),
        os.path.join(CONF.state_path, config_path),
        "/etc/cinder/%s" % config_path,
    ]

    for path in possible_locations:
        if os.path.exists(path):
            return os.path.abspath(path)

    raise exception.ConfigNotFound(path=os.path.abspath(config_path))


def as_int(obj, quiet=True):
    # Try "2" -> 2
    try:
        return int(obj)
    except (ValueError, TypeError):
        pass
    # Try "2.5" -> 2
    try:
        return int(float(obj))
    except (ValueError, TypeError):
        pass
    # Eck, not sure what this is then.
    if not quiet:
        raise TypeError(_("Can not translate %s to integer.") % (obj))
    return obj


def check_exclusive_options(**kwargs):
    """Checks that only one of the provided options is actually not-none.

    Iterates over all the kwargs passed in and checks that only one of said
    arguments is not-none, if more than one is not-none then an exception will
    be raised with the names of those arguments who were not-none.
    """

    if not kwargs:
        return

    pretty_keys = kwargs.pop("pretty_keys", True)
    exclusive_options = {}
    for (k, v) in kwargs.iteritems():
        if v is not None:
            exclusive_options[k] = True

    if len(exclusive_options) > 1:
        # Change the format of the names from pythonic to
        # something that is more readable.
        #
        # Ex: 'the_key' -> 'the key'
        if pretty_keys:
            names = [k.replace('_', ' ') for k in kwargs.keys()]
        else:
            names = kwargs.keys()
        names = ", ".join(sorted(names))
        msg = (_("May specify only one of %s") % (names))
        raise exception.InvalidInput(reason=msg)


def execute(*cmd, **kwargs):
    """Convenience wrapper around oslo's execute() method."""
    if 'run_as_root' in kwargs and not 'root_helper' in kwargs:
        kwargs['root_helper'] = get_root_helper()
    return processutils.execute(*cmd, **kwargs)


def check_ssh_injection(cmd_list):
    ssh_injection_pattern = ['`', '$', '|', '||', ';', '&', '&&', '>', '>>',
                             '<']

    # Check whether injection attacks exist
    for arg in cmd_list:
        arg = arg.strip()

        # Check for matching quotes on the ends
        is_quoted = re.match('^(?P<quote>[\'"])(?P<quoted>.*)(?P=quote)$', arg)
        if is_quoted:
            # Check for unescaped quotes within the quoted argument
            quoted = is_quoted.group('quoted')
            if quoted:
                if (re.match('[\'"]', quoted) or
                        re.search('[^\\\\][\'"]', quoted)):
                    raise exception.SSHInjectionThreat(command=str(cmd_list))
        else:
            # We only allow spaces within quoted arguments, and that
            # is the only special character allowed within quotes
            if len(arg.split()) > 1:
                raise exception.SSHInjectionThreat(command=str(cmd_list))

        # Second, check whether danger character in command. So the shell
        # special operator must be a single argument.
        for c in ssh_injection_pattern:
            if arg == c:
                continue

            result = arg.find(c)
            if not result == -1:
                if result == 0 or not arg[result - 1] == '\\':
                    raise exception.SSHInjectionThreat(command=cmd_list)


def create_channel(client, width, height):
    """Invoke an interactive shell session on server."""
    channel = client.invoke_shell()
    channel.resize_pty(width, height)
    return channel


class SSHPool(pools.Pool):
    """A simple eventlet pool to hold ssh connections."""

    def __init__(self, ip, port, conn_timeout, login, password=None,
                 privatekey=None, *args, **kwargs):
        self.ip = ip
        self.port = port
        self.login = login
        self.password = password
        self.conn_timeout = conn_timeout if conn_timeout else None
        self.privatekey = privatekey
        super(SSHPool, self).__init__(*args, **kwargs)

    def create(self):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if self.password:
                ssh.connect(self.ip,
                            port=self.port,
                            username=self.login,
                            password=self.password,
                            timeout=self.conn_timeout)
            elif self.privatekey:
                pkfile = os.path.expanduser(self.privatekey)
                privatekey = paramiko.RSAKey.from_private_key_file(pkfile)
                ssh.connect(self.ip,
                            port=self.port,
                            username=self.login,
                            pkey=privatekey,
                            timeout=self.conn_timeout)
            else:
                msg = _("Specify a password or private_key")
                raise exception.CinderException(msg)

            # Paramiko by default sets the socket timeout to 0.1 seconds,
            # ignoring what we set thru the sshclient. This doesn't help for
            # keeping long lived connections. Hence we have to bypass it, by
            # overriding it after the transport is initialized. We are setting
            # the sockettimeout to None and setting a keepalive packet so that,
            # the server will keep the connection open. All that does is send
            # a keepalive packet every ssh_conn_timeout seconds.
            if self.conn_timeout:
                transport = ssh.get_transport()
                transport.sock.settimeout(None)
                transport.set_keepalive(self.conn_timeout)
            return ssh
        except Exception as e:
            msg = _("Error connecting via ssh: %s") % e
            LOG.error(msg)
            raise paramiko.SSHException(msg)

    def get(self):
        """
        Return an item from the pool, when one is available.  This may
        cause the calling greenthread to block. Check if a connection is active
        before returning it. For dead connections create and return a new
        connection.
        """
        conn = super(SSHPool, self).get()
        if conn:
            if conn.get_transport().is_active():
                return conn
            else:
                conn.close()
        return self.create()

    def remove(self, ssh):
        """Close an ssh client and remove it from free_items."""
        ssh.close()
        ssh = None
        if ssh in self.free_items:
            self.free_items.pop(ssh)
        if self.current_size > 0:
            self.current_size -= 1


def cinderdir():
    import cinder
    return os.path.abspath(cinder.__file__).split('cinder/__init__.py')[0]


# Default symbols to use for passwords. Avoids visually confusing characters.
# ~6 bits per symbol
DEFAULT_PASSWORD_SYMBOLS = ('23456789',  # Removed: 0,1
                            'ABCDEFGHJKLMNPQRSTUVWXYZ',   # Removed: I, O
                            'abcdefghijkmnopqrstuvwxyz')  # Removed: l


# ~5 bits per symbol
EASIER_PASSWORD_SYMBOLS = ('23456789',  # Removed: 0, 1
                           'ABCDEFGHJKLMNPQRSTUVWXYZ')  # Removed: I, O


def last_completed_audit_period(unit=None):
    """This method gives you the most recently *completed* audit period.

    arguments:
            units: string, one of 'hour', 'day', 'month', 'year'
                    Periods normally begin at the beginning (UTC) of the
                    period unit (So a 'day' period begins at midnight UTC,
                    a 'month' unit on the 1st, a 'year' on Jan, 1)
                    unit string may be appended with an optional offset
                    like so:  'day@18'  This will begin the period at 18:00
                    UTC.  'month@15' starts a monthly period on the 15th,
                    and year@3 begins a yearly one on March 1st.


    returns:  2 tuple of datetimes (begin, end)
              The begin timestamp of this audit period is the same as the
              end of the previous.
    """
    if not unit:
        unit = CONF.volume_usage_audit_period

    offset = 0
    if '@' in unit:
        unit, offset = unit.split("@", 1)
        offset = int(offset)

    rightnow = timeutils.utcnow()
    if unit not in ('month', 'day', 'year', 'hour'):
        raise ValueError('Time period must be hour, day, month or year')
    if unit == 'month':
        if offset == 0:
            offset = 1
        end = datetime.datetime(day=offset,
                                month=rightnow.month,
                                year=rightnow.year)
        if end >= rightnow:
            year = rightnow.year
            if 1 >= rightnow.month:
                year -= 1
                month = 12 + (rightnow.month - 1)
            else:
                month = rightnow.month - 1
            end = datetime.datetime(day=offset,
                                    month=month,
                                    year=year)
        year = end.year
        if 1 >= end.month:
            year -= 1
            month = 12 + (end.month - 1)
        else:
            month = end.month - 1
        begin = datetime.datetime(day=offset, month=month, year=year)

    elif unit == 'year':
        if offset == 0:
            offset = 1
        end = datetime.datetime(day=1, month=offset, year=rightnow.year)
        if end >= rightnow:
            end = datetime.datetime(day=1,
                                    month=offset,
                                    year=rightnow.year - 1)
            begin = datetime.datetime(day=1,
                                      month=offset,
                                      year=rightnow.year - 2)
        else:
            begin = datetime.datetime(day=1,
                                      month=offset,
                                      year=rightnow.year - 1)

    elif unit == 'day':
        end = datetime.datetime(hour=offset,
                                day=rightnow.day,
                                month=rightnow.month,
                                year=rightnow.year)
        if end >= rightnow:
            end = end - datetime.timedelta(days=1)
        begin = end - datetime.timedelta(days=1)

    elif unit == 'hour':
        end = rightnow.replace(minute=offset, second=0, microsecond=0)
        if end >= rightnow:
            end = end - datetime.timedelta(hours=1)
        begin = end - datetime.timedelta(hours=1)

    return (begin, end)


def generate_password(length=20, symbolgroups=DEFAULT_PASSWORD_SYMBOLS):
    """Generate a random password from the supplied symbol groups.

    At least one symbol from each group will be included. Unpredictable
    results if length is less than the number of symbol groups.

    Believed to be reasonably secure (with a reasonable password length!)

    """
    r = random.SystemRandom()

    # NOTE(jerdfelt): Some password policies require at least one character
    # from each group of symbols, so start off with one random character
    # from each symbol group
    password = [r.choice(s) for s in symbolgroups]
    # If length < len(symbolgroups), the leading characters will only
    # be from the first length groups. Try our best to not be predictable
    # by shuffling and then truncating.
    r.shuffle(password)
    password = password[:length]
    length -= len(password)

    # then fill with random characters from all symbol groups
    symbols = ''.join(symbolgroups)
    password.extend([r.choice(symbols) for _i in xrange(length)])

    # finally shuffle to ensure first x characters aren't from a
    # predictable group
    r.shuffle(password)

    return ''.join(password)


def generate_username(length=20, symbolgroups=DEFAULT_PASSWORD_SYMBOLS):
    # Use the same implementation as the password generation.
    return generate_password(length, symbolgroups)


class LazyPluggable(object):
    """A pluggable backend loaded lazily based on some value."""

    def __init__(self, pivot, **backends):
        self.__backends = backends
        self.__pivot = pivot
        self.__backend = None

    def __get_backend(self):
        if not self.__backend:
            backend_name = CONF[self.__pivot]
            if backend_name not in self.__backends:
                raise exception.Error(_('Invalid backend: %s') % backend_name)

            backend = self.__backends[backend_name]
            if isinstance(backend, tuple):
                name = backend[0]
                fromlist = backend[1]
            else:
                name = backend
                fromlist = backend

            self.__backend = __import__(name, None, None, fromlist)
            LOG.debug(_('backend %s'), self.__backend)
        return self.__backend

    def __getattr__(self, key):
        backend = self.__get_backend()
        return getattr(backend, key)


class LoopingCallDone(Exception):
    """Exception to break out and stop a LoopingCall.

    The poll-function passed to LoopingCall can raise this exception to
    break out of the loop normally. This is somewhat analogous to
    StopIteration.

    An optional return-value can be included as the argument to the exception;
    this return-value will be returned by LoopingCall.wait()

    """

    def __init__(self, retvalue=True):
        """:param retvalue: Value that LoopingCall.wait() should return."""
        self.retvalue = retvalue


class LoopingCall(object):
    def __init__(self, f=None, *args, **kw):
        self.args = args
        self.kw = kw
        self.f = f
        self._running = False

    def start(self, interval, initial_delay=None):
        self._running = True
        done = event.Event()

        def _inner():
            if initial_delay:
                greenthread.sleep(initial_delay)

            try:
                while self._running:
                    self.f(*self.args, **self.kw)
                    if not self._running:
                        break
                    greenthread.sleep(interval)
            except LoopingCallDone as e:
                self.stop()
                done.send(e.retvalue)
            except Exception:
                LOG.exception(_('in looping call'))
                done.send_exception(*sys.exc_info())
                return
            else:
                done.send(True)

        self.done = done

        greenthread.spawn(_inner)
        return self.done

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()


class ProtectedExpatParser(expatreader.ExpatParser):
    """An expat parser which disables DTD's and entities by default."""

    def __init__(self, forbid_dtd=True, forbid_entities=True,
                 *args, **kwargs):
        # Python 2.x old style class
        expatreader.ExpatParser.__init__(self, *args, **kwargs)
        self.forbid_dtd = forbid_dtd
        self.forbid_entities = forbid_entities

    def start_doctype_decl(self, name, sysid, pubid, has_internal_subset):
        raise ValueError("Inline DTD forbidden")

    def entity_decl(self, entityName, is_parameter_entity, value, base,
                    systemId, publicId, notationName):
        raise ValueError("<!ENTITY> forbidden")

    def unparsed_entity_decl(self, name, base, sysid, pubid, notation_name):
        # expat 1.2
        raise ValueError("<!ENTITY> forbidden")

    def reset(self):
        expatreader.ExpatParser.reset(self)
        if self.forbid_dtd:
            self._parser.StartDoctypeDeclHandler = self.start_doctype_decl
        if self.forbid_entities:
            self._parser.EntityDeclHandler = self.entity_decl
            self._parser.UnparsedEntityDeclHandler = self.unparsed_entity_decl


def safe_minidom_parse_string(xml_string):
    """Parse an XML string using minidom safely.

    """
    try:
        return minidom.parseString(xml_string, parser=ProtectedExpatParser())
    except sax.SAXParseException as se:
        raise expat.ExpatError()


def xhtml_escape(value):
    """Escapes a string so it is valid within XML or XHTML.

    """
    return saxutils.escape(value, {'"': '&quot;', "'": '&apos;'})


def get_from_path(items, path):
    """Returns a list of items matching the specified path.

    Takes an XPath-like expression e.g. prop1/prop2/prop3, and for each item
    in items, looks up items[prop1][prop2][prop3]. Like XPath, if any of the
    intermediate results are lists it will treat each list item individually.
    A 'None' in items or any child expressions will be ignored, this function
    will not throw because of None (anywhere) in items.  The returned list
    will contain no None values.

    """
    if path is None:
        raise exception.Error('Invalid mini_xpath')

    (first_token, sep, remainder) = path.partition('/')

    if first_token == '':
        raise exception.Error('Invalid mini_xpath')

    results = []

    if items is None:
        return results

    if not isinstance(items, list):
        # Wrap single objects in a list
        items = [items]

    for item in items:
        if item is None:
            continue
        get_method = getattr(item, 'get', None)
        if get_method is None:
            continue
        child = get_method(first_token)
        if child is None:
            continue
        if isinstance(child, list):
            # Flatten intermediate lists
            for x in child:
                results.append(x)
        else:
            results.append(child)

    if not sep:
        # No more tokens
        return results
    else:
        return get_from_path(results, remainder)


def is_valid_boolstr(val):
    """Check if the provided string is a valid bool string or not."""
    val = str(val).lower()
    return (val == 'true' or val == 'false' or
            val == 'yes' or val == 'no' or
            val == 'y' or val == 'n' or
            val == '1' or val == '0')


def monkey_patch():
    """If the CONF.monkey_patch set as True,
    this function patches a decorator
    for all functions in specified modules.

    You can set decorators for each modules
    using CONF.monkey_patch_modules.
    The format is "Module path:Decorator function".
    Example: 'cinder.api.ec2.cloud:' \
     cinder.openstack.common.notifier.api.notify_decorator'

    Parameters of the decorator is as follows.
    (See cinder.openstack.common.notifier.api.notify_decorator)

    name - name of the function
    function - object of the function
    """
    # If CONF.monkey_patch is not True, this function do nothing.
    if not CONF.monkey_patch:
        return
    # Get list of modules and decorators
    for module_and_decorator in CONF.monkey_patch_modules:
        module, decorator_name = module_and_decorator.split(':')
        # import decorator function
        decorator = importutils.import_class(decorator_name)
        __import__(module)
        # Retrieve module information using pyclbr
        module_data = pyclbr.readmodule_ex(module)
        for key in module_data.keys():
            # set the decorator for the class methods
            if isinstance(module_data[key], pyclbr.Class):
                clz = importutils.import_class("%s.%s" % (module, key))
                for method, func in inspect.getmembers(clz, inspect.ismethod):
                    setattr(
                        clz, method,
                        decorator("%s.%s.%s" % (module, key, method), func))
            # set the decorator for the function
            if isinstance(module_data[key], pyclbr.Function):
                func = importutils.import_class("%s.%s" % (module, key))
                setattr(sys.modules[module], key,
                        decorator("%s.%s" % (module, key), func))


def generate_glance_url():
    """Generate the URL to glance."""
    # TODO(jk0): This will eventually need to take SSL into consideration
    # when supported in glance.
    return "http://%s:%d" % (CONF.glance_host, CONF.glance_port)


def make_dev_path(dev, partition=None, base='/dev'):
    """Return a path to a particular device.

    >>> make_dev_path('xvdc')
    /dev/xvdc

    >>> make_dev_path('xvdc', 1)
    /dev/xvdc1
    """
    path = os.path.join(base, dev)
    if partition:
        path += str(partition)
    return path


def total_seconds(td):
    """Local total_seconds implementation for compatibility with python 2.6"""
    if hasattr(td, 'total_seconds'):
        return td.total_seconds()
    else:
        return ((td.days * 86400 + td.seconds) * 10 ** 6 +
                td.microseconds) / 10.0 ** 6


def sanitize_hostname(hostname):
    """Return a hostname which conforms to RFC-952 and RFC-1123 specs."""
    if isinstance(hostname, unicode):
        hostname = hostname.encode('latin-1', 'ignore')

    hostname = re.sub('[ _]', '-', hostname)
    hostname = re.sub('[^\w.-]+', '', hostname)
    hostname = hostname.lower()
    hostname = hostname.strip('.-')

    return hostname


def read_cached_file(filename, cache_info, reload_func=None):
    """Read from a file if it has been modified.

    :param cache_info: dictionary to hold opaque cache.
    :param reload_func: optional function to be called with data when
                        file is reloaded due to a modification.

    :returns: data from file

    """
    mtime = os.path.getmtime(filename)
    if not cache_info or mtime != cache_info.get('mtime'):
        with open(filename) as fap:
            cache_info['data'] = fap.read()
        cache_info['mtime'] = mtime
        if reload_func:
            reload_func(cache_info['data'])
    return cache_info['data']


def hash_file(file_like_object):
    """Generate a hash for the contents of a file."""
    checksum = hashlib.sha1()
    any(map(checksum.update, iter(lambda: file_like_object.read(32768), '')))
    return checksum.hexdigest()


def service_is_up(service):
    """Check whether a service is up based on last heartbeat."""
    last_heartbeat = service['updated_at'] or service['created_at']
    # Timestamps in DB are UTC.
    elapsed = total_seconds(timeutils.utcnow() - last_heartbeat)
    return abs(elapsed) <= CONF.service_down_time


def read_file_as_root(file_path):
    """Secure helper to read file as root."""
    try:
        out, _err = execute('cat', file_path, run_as_root=True)
        return out
    except processutils.ProcessExecutionError:
        raise exception.FileNotFound(file_path=file_path)


@contextlib.contextmanager
def temporary_chown(path, owner_uid=None):
    """Temporarily chown a path.

    :params owner_uid: UID of temporary owner (defaults to current user)
    """
    if owner_uid is None:
        owner_uid = os.getuid()

    orig_uid = os.stat(path).st_uid

    if orig_uid != owner_uid:
        execute('chown', owner_uid, path, run_as_root=True)
    try:
        yield
    finally:
        if orig_uid != owner_uid:
            execute('chown', orig_uid, path, run_as_root=True)


@contextlib.contextmanager
def tempdir(**kwargs):
    tmpdir = tempfile.mkdtemp(**kwargs)
    try:
        yield tmpdir
    finally:
        try:
            shutil.rmtree(tmpdir)
        except OSError as e:
            LOG.debug(_('Could not remove tmpdir: %s'), str(e))


def walk_class_hierarchy(clazz, encountered=None):
    """Walk class hierarchy, yielding most derived classes first"""
    if not encountered:
        encountered = []
    for subclass in clazz.__subclasses__():
        if subclass not in encountered:
            encountered.append(subclass)
            # drill down to leaves first
            for subsubclass in walk_class_hierarchy(subclass, encountered):
                yield subsubclass
            yield subclass


def get_root_helper():
    return 'sudo cinder-rootwrap %s' % CONF.rootwrap_config


def brick_get_connector_properties():
    """wrapper for the brick calls to automatically set
    the root_helper needed for cinder.
    """

    root_helper = get_root_helper()
    return connector.get_connector_properties(root_helper,
                                              CONF.my_ip)


def brick_get_connector(protocol, driver=None,
                        execute=processutils.execute,
                        use_multipath=False,
                        device_scan_attempts=3):
    """Wrapper to get a brick connector object.
    This automatically populates the required protocol as well
    as the root_helper needed to execute commands.
    """

    root_helper = get_root_helper()
    return connector.InitiatorConnector.factory(protocol, root_helper,
                                                driver=driver,
                                                execute=execute,
                                                use_multipath=use_multipath,
                                                device_scan_attempts=
                                                device_scan_attempts)


def require_driver_initialized(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        # we can't do anything if the driver didn't init
        if not self.driver.initialized:
            driver_name = self.driver.__class__.__name__
            raise exception.DriverNotInitialized(driver=driver_name)
        return func(self, *args, **kwargs)
    return wrapper
