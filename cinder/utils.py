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

from collections import OrderedDict
import contextlib
import datetime
import functools
import inspect
import math
import multiprocessing
import operator
import os
import pyclbr
import re
import shutil
import stat
import sys
import tempfile

import eventlet
from eventlet import tpool
from oslo_concurrency import lockutils
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import strutils
from oslo_utils import timeutils
import tenacity

from cinder import exception
from cinder.i18n import _

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
ISO_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"
PERFECT_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"
INITIAL_AUTO_MOSR = 20
INFINITE_UNKNOWN_VALUES = ('infinite', 'unknown')


synchronized = lockutils.synchronized_with_prefix('cinder-')


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
    for (k, v) in kwargs.items():
        if v is not None:
            exclusive_options[k] = True

    if len(exclusive_options) > 1:
        # Change the format of the names from pythonic to
        # something that is more readable.
        #
        # Ex: 'the_key' -> 'the key'
        if pretty_keys:
            names = [k.replace('_', ' ') for k in kwargs]
        else:
            names = kwargs.keys()
        names = ", ".join(sorted(names))
        msg = (_("May specify only one of %s") % (names))
        raise exception.InvalidInput(reason=msg)


def execute(*cmd, **kwargs):
    """Convenience wrapper around oslo's execute() method."""
    if 'run_as_root' in kwargs and 'root_helper' not in kwargs:
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
                    raise exception.SSHInjectionThreat(command=cmd_list)
        else:
            # We only allow spaces within quoted arguments, and that
            # is the only special character allowed within quotes
            if len(arg.split()) > 1:
                raise exception.SSHInjectionThreat(command=cmd_list)

        # Second, check whether danger character in command. So the shell
        # special operator must be a single argument.
        for c in ssh_injection_pattern:
            if c not in arg:
                continue

            result = arg.find(c)
            if not result == -1:
                if result == 0 or not arg[result - 1] == '\\':
                    raise exception.SSHInjectionThreat(command=cmd_list)


def check_metadata_properties(metadata=None):
    """Checks that the volume metadata properties are valid."""

    if not metadata:
        metadata = {}
    if not isinstance(metadata, dict):
        msg = _("Metadata should be a dict.")
        raise exception.InvalidInput(msg)

    for k, v in metadata.items():
        try:
            check_string_length(k, "Metadata key: %s" % k, min_length=1)
            check_string_length(v, "Value for metadata key: %s" % k)
        except exception.InvalidInput as exc:
            raise exception.InvalidVolumeMetadata(reason=exc)
        # for backward compatibility
        if len(k) > 255:
            msg = _("Metadata property key %s greater than 255 "
                    "characters.") % k
            raise exception.InvalidVolumeMetadataSize(reason=msg)
        if len(v) > 255:
            msg = _("Metadata property key %s value greater than "
                    "255 characters.") % k
            raise exception.InvalidVolumeMetadataSize(reason=msg)


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


def monkey_patch():
    """Patches decorators for all functions in a specified module.

    If the CONF.monkey_patch set as True,
    this function patches a decorator
    for all functions in specified modules.

    You can set decorators for each modules
    using CONF.monkey_patch_modules.
    The format is "Module path:Decorator function".
    Example: 'cinder.api.ec2.cloud:' \
     cinder.openstack.common.notifier.api.notify_decorator'

    Parameters of the decorator are as follows.
    (See cinder.openstack.common.notifier.api.notify_decorator)

    :param name: name of the function
    :param function: object of the function
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
                # On Python 3, unbound methods are regular functions
                predicate = inspect.isfunction
                for method, func in inspect.getmembers(clz, predicate):
                    setattr(
                        clz, method,
                        decorator("%s.%s.%s" % (module, key, method), func))
            # set the decorator for the function
            elif isinstance(module_data[key], pyclbr.Function):
                func = importutils.import_class("%s.%s" % (module, key))
                setattr(sys.modules[module], key,
                        decorator("%s.%s" % (module, key), func))


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


def robust_file_write(directory, filename, data):
    """Robust file write.

    Use "write to temp file and rename" model for writing the
    persistence file.

    :param directory: Target directory to create a file.
    :param filename: File name to store specified data.
    :param data: String data.
    """
    tempname = None
    dirfd = None
    try:
        dirfd = os.open(directory, os.O_DIRECTORY)

        # write data to temporary file
        with tempfile.NamedTemporaryFile(prefix=filename,
                                         dir=directory,
                                         delete=False) as tf:
            tempname = tf.name
            tf.write(data.encode('utf-8'))
            tf.flush()
            os.fdatasync(tf.fileno())
            tf.close()

            # Fsync the directory to ensure the fact of the existence of
            # the temp file hits the disk.
            os.fsync(dirfd)
            # If destination file exists, it will be replaced silently.
            os.rename(tempname, os.path.join(directory, filename))
            # Fsync the directory to ensure the rename hits the disk.
            os.fsync(dirfd)
    except OSError:
        with excutils.save_and_reraise_exception():
            LOG.error("Failed to write persistence file: %(path)s.",
                      {'path': os.path.join(directory, filename)})
            if os.path.isfile(tempname):
                os.unlink(tempname)
    finally:
        if dirfd:
            os.close(dirfd)


@contextlib.contextmanager
def temporary_chown(path, owner_uid=None):
    """Temporarily chown a path.

    :params owner_uid: UID of temporary owner (defaults to current user)
    """

    if os.name == 'nt':
        LOG.debug("Skipping chown for %s as this operation is "
                  "not available on Windows.", path)
        yield
        return

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
            LOG.debug('Could not remove tmpdir: %s', str(e))


def get_root_helper():
    return 'sudo cinder-rootwrap %s' % CONF.rootwrap_config


def require_driver_initialized(driver):
    """Verifies if `driver` is initialized

    If the driver is not initialized, an exception will be raised.

    :params driver: The driver instance.
    :raises: `exception.DriverNotInitialized`
    """
    # we can't do anything if the driver didn't init
    if not driver.initialized:
        driver_name = driver.__class__.__name__
        LOG.error("Volume driver %s not initialized", driver_name)
        raise exception.DriverNotInitialized()
    else:
        log_unsupported_driver_warning(driver)


def log_unsupported_driver_warning(driver):
    """Annoy the log about unsupported drivers."""
    if not driver.supported:
        # Check to see if the driver is flagged as supported.
        LOG.warning("Volume driver (%(driver_name)s %(version)s) is "
                    "currently unsupported and may be removed in the "
                    "next release of OpenStack.  Use at your own risk.",
                    {'driver_name': driver.__class__.__name__,
                     'version': driver.get_version()},
                    resource={'type': 'driver',
                              'id': driver.__class__.__name__})


def get_file_mode(path):
    """This primarily exists to make unit testing easier."""
    return stat.S_IMODE(os.stat(path).st_mode)


def get_file_gid(path):
    """This primarily exists to make unit testing easier."""
    return os.stat(path).st_gid


def get_file_size(path):
    """Returns the file size."""
    return os.stat(path).st_size


def _get_disk_of_partition(devpath, st=None):
    """Gets a disk device path and status from partition path.

    Returns a disk device path from a partition device path, and stat for
    the device. If devpath is not a partition, devpath is returned as it is.
    For example, '/dev/sda' is returned for '/dev/sda1', and '/dev/disk1' is
    for '/dev/disk1p1' ('p' is prepended to the partition number if the disk
    name ends with numbers).
    """
    diskpath = re.sub(r'(?:(?<=\d)p)?\d+$', '', devpath)
    if diskpath != devpath:
        try:
            st_disk = os.stat(diskpath)
            if stat.S_ISBLK(st_disk.st_mode):
                return (diskpath, st_disk)
        except OSError:
            pass
    # devpath is not a partition
    if st is None:
        st = os.stat(devpath)
    return (devpath, st)


def get_bool_param(param_string, params, default=False):
    param = params.get(param_string, default)
    if not strutils.is_valid_boolstr(param):
        msg = _("Value '%(param)s' for '%(param_string)s' is not "
                "a boolean.") % {'param': param, 'param_string': param_string}
        raise exception.InvalidParameterValue(err=msg)

    return strutils.bool_from_string(param, strict=True)


def get_blkdev_major_minor(path, lookup_for_file=True):
    """Get 'major:minor' number of block device.

    Get the device's 'major:minor' number of a block device to control
    I/O ratelimit of the specified path.
    If lookup_for_file is True and the path is a regular file, lookup a disk
    device which the file lies on and returns the result for the device.
    """
    st = os.stat(path)
    if stat.S_ISBLK(st.st_mode):
        path, st = _get_disk_of_partition(path, st)
        return '%d:%d' % (os.major(st.st_rdev), os.minor(st.st_rdev))
    elif stat.S_ISCHR(st.st_mode):
        # No I/O ratelimit control is provided for character devices
        return None
    elif lookup_for_file:
        # lookup the mounted disk which the file lies on
        out, _err = execute('df', path)
        devpath = out.split("\n")[1].split()[0]
        if devpath[0] != '/':
            # the file is on a network file system
            return None
        return get_blkdev_major_minor(devpath, False)
    else:
        msg = _("Unable to get a block device for file \'%s\'") % path
        raise exception.CinderException(msg)


def check_string_length(value, name, min_length=0, max_length=None,
                        allow_all_spaces=True):
    """Check the length of specified string.

    :param value: the value of the string
    :param name: the name of the string
    :param min_length: the min_length of the string
    :param max_length: the max_length of the string
    """
    try:
        strutils.check_string_length(value, name=name,
                                     min_length=min_length,
                                     max_length=max_length)
    except(ValueError, TypeError) as exc:
        raise exception.InvalidInput(reason=exc)

    if not allow_all_spaces and value.isspace():
        msg = _('%(name)s cannot be all spaces.')
        raise exception.InvalidInput(reason=msg)


def is_blk_device(dev):
    try:
        if stat.S_ISBLK(os.stat(dev).st_mode):
            return True
        return False
    except Exception:
        LOG.debug('Path %s not found in is_blk_device check', dev)
        return False


class ComparableMixin(object):
    def _compare(self, other, method):
        try:
            return method(self._cmpkey(), other._cmpkey())
        except (AttributeError, TypeError):
            # _cmpkey not implemented, or return different type,
            # so I can't compare with "other".
            return NotImplemented

    def __lt__(self, other):
        return self._compare(other, lambda s, o: s < o)

    def __le__(self, other):
        return self._compare(other, lambda s, o: s <= o)

    def __eq__(self, other):
        return self._compare(other, lambda s, o: s == o)

    def __ge__(self, other):
        return self._compare(other, lambda s, o: s >= o)

    def __gt__(self, other):
        return self._compare(other, lambda s, o: s > o)

    def __ne__(self, other):
        return self._compare(other, lambda s, o: s != o)


class retry_if_exit_code(tenacity.retry_if_exception):
    """Retry on ProcessExecutionError specific exit codes."""
    def __init__(self, codes):
        self.codes = (codes,) if isinstance(codes, int) else codes
        super(retry_if_exit_code, self).__init__(self._check_exit_code)

    def _check_exit_code(self, exc):
        return (exc and isinstance(exc, processutils.ProcessExecutionError) and
                exc.exit_code in self.codes)


def retry(retry_param, interval=1, retries=3, backoff_rate=2,
          wait_random=False, retry=tenacity.retry_if_exception_type):

    if retries < 1:
        raise ValueError('Retries must be greater than or '
                         'equal to 1 (received: %s). ' % retries)

    if wait_random:
        wait = tenacity.wait_random_exponential(multiplier=interval)
    else:
        wait = tenacity.wait_exponential(
            multiplier=interval, min=0, exp_base=backoff_rate)

    def _decorator(f):

        @functools.wraps(f)
        def _wrapper(*args, **kwargs):
            r = tenacity.Retrying(
                sleep=tenacity.nap.sleep,
                before_sleep=tenacity.before_sleep_log(LOG, logging.DEBUG),
                after=tenacity.after_log(LOG, logging.DEBUG),
                stop=tenacity.stop_after_attempt(retries),
                reraise=True,
                retry=retry(retry_param),
                wait=wait)
            return r.call(f, *args, **kwargs)

        return _wrapper

    return _decorator


def convert_str(text):
    """Convert to native string.

    Convert bytes and Unicode strings to native strings:

    * convert to bytes on Python 2:
      encode Unicode using encodeutils.safe_encode()
    * convert to Unicode on Python 3: decode bytes from UTF-8
    """
    if isinstance(text, bytes):
        return text.decode('utf-8')
    else:
        return text


def build_or_str(elements, str_format=None):
    """Builds a string of elements joined by 'or'.

    Will join strings with the 'or' word and if a str_format is provided it
    will be used to format the resulted joined string.
    If there are no elements an empty string will be returned.

    :param elements: Elements we want to join.
    :type elements: String or iterable of strings.
    :param str_format: String to use to format the response.
    :type str_format: String.
    """
    if not elements:
        return ''

    if not isinstance(elements, str):
        elements = _(' or ').join(elements)

    if str_format:
        return str_format % elements
    return elements


def calculate_virtual_free_capacity(total_capacity,
                                    free_capacity,
                                    provisioned_capacity,
                                    thin_provisioning_support,
                                    max_over_subscription_ratio,
                                    reserved_percentage,
                                    thin):
    """Calculate the virtual free capacity based on thin provisioning support.

    :param total_capacity:  total_capacity_gb of a host_state or pool.
    :param free_capacity:   free_capacity_gb of a host_state or pool.
    :param provisioned_capacity:    provisioned_capacity_gb of a host_state
                                    or pool.
    :param thin_provisioning_support:   thin_provisioning_support of
                                        a host_state or a pool.
    :param max_over_subscription_ratio: max_over_subscription_ratio of
                                        a host_state or a pool
    :param reserved_percentage: reserved_percentage of a host_state or
                                a pool.
    :param thin: whether volume to be provisioned is thin
    :returns: the calculated virtual free capacity.
    """

    total = float(total_capacity)
    reserved = float(reserved_percentage) / 100

    if thin and thin_provisioning_support:
        free = (total * max_over_subscription_ratio
                - provisioned_capacity
                - math.floor(total * reserved))
    else:
        # Calculate how much free space is left after taking into
        # account the reserved space.
        free = free_capacity - math.floor(total * reserved)
    return free


def calculate_max_over_subscription_ratio(capability,
                                          global_max_over_subscription_ratio):
    # provisioned_capacity_gb is the apparent total capacity of
    # all the volumes created on a backend, which is greater than
    # or equal to allocated_capacity_gb, which is the apparent
    # total capacity of all the volumes created on a backend
    # in Cinder. Using allocated_capacity_gb as the default of
    # provisioned_capacity_gb if it is not set.
    allocated_capacity_gb = capability.get('allocated_capacity_gb', 0)
    provisioned_capacity_gb = capability.get('provisioned_capacity_gb',
                                             allocated_capacity_gb)
    thin_provisioning_support = capability.get('thin_provisioning_support',
                                               False)
    total_capacity_gb = capability.get('total_capacity_gb', 0)
    free_capacity_gb = capability.get('free_capacity_gb', 0)
    pool_name = capability.get('pool_name',
                               capability.get('volume_backend_name'))

    # If thin provisioning is not supported the capacity filter will not use
    # the value we return, no matter what it is.
    if not thin_provisioning_support:
        LOG.debug("Trying to retrieve max_over_subscription_ratio from a "
                  "service that does not support thin provisioning")
        return 1.0

    # Again, if total or free capacity is infinite or unknown, the capacity
    # filter will not use the max_over_subscription_ratio at all. So, does
    # not matter what we return here.
    if ((total_capacity_gb in INFINITE_UNKNOWN_VALUES) or
            (free_capacity_gb in INFINITE_UNKNOWN_VALUES)):
        return 1.0

    max_over_subscription_ratio = (capability.get(
        'max_over_subscription_ratio') or global_max_over_subscription_ratio)

    # We only calculate the automatic max_over_subscription_ratio (mosr)
    # when the global or driver conf is set auto and while
    # provisioned_capacity_gb is not 0. When auto is set and
    # provisioned_capacity_gb is 0, we use the default value 20.0.
    if max_over_subscription_ratio == 'auto':
        if provisioned_capacity_gb != 0:
            used_capacity = total_capacity_gb - free_capacity_gb
            LOG.debug("Calculating max_over_subscription_ratio for "
                      "pool %s: provisioned_capacity_gb=%s, "
                      "used_capacity=%s",
                      pool_name, provisioned_capacity_gb, used_capacity)
            max_over_subscription_ratio = 1 + (
                float(provisioned_capacity_gb) / (used_capacity + 1))
        else:
            max_over_subscription_ratio = INITIAL_AUTO_MOSR

        LOG.info("Auto max_over_subscription_ratio for pool %s is "
                 "%s", pool_name, max_over_subscription_ratio)
    else:
        max_over_subscription_ratio = float(max_over_subscription_ratio)

    return max_over_subscription_ratio


def validate_dictionary_string_length(specs):
    """Check the length of each key and value of dictionary."""
    if not isinstance(specs, dict):
        msg = _('specs must be a dictionary.')
        raise exception.InvalidInput(reason=msg)

    for key, value in specs.items():
        if key is not None:
            check_string_length(key, 'Key "%s"' % key,
                                min_length=1, max_length=255)

        if value is not None:
            check_string_length(value, 'Value for key "%s"' % key,
                                min_length=0, max_length=255)


def service_expired_time(with_timezone=False):
    return (timeutils.utcnow(with_timezone=with_timezone) -
            datetime.timedelta(seconds=CONF.service_down_time))


class DoNothing(str):
    """Class that literrally does nothing.

    We inherit from str in case it's called with json.dumps.
    """
    def __call__(self, *args, **kwargs):
        return self

    def __getattr__(self, name):
        return self


DO_NOTHING = DoNothing()


def notifications_enabled(conf):
    """Check if oslo notifications are enabled."""
    notifications_driver = set(conf.oslo_messaging_notifications.driver)
    return notifications_driver and notifications_driver != {'noop'}


def if_notifications_enabled(f):
    """Calls decorated method only if notifications are enabled."""
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if notifications_enabled(CONF):
            return f(*args, **kwargs)
        return DO_NOTHING
    return wrapped


LOG_LEVELS = ('INFO', 'WARNING', 'ERROR', 'DEBUG')


def get_log_method(level_string):
    level_string = level_string or ''
    upper_level_string = level_string.upper()
    if upper_level_string not in LOG_LEVELS:
        raise exception.InvalidInput(
            reason=_('%s is not a valid log level.') % level_string)
    return getattr(logging, upper_level_string)


def set_log_levels(prefix, level_string):
    level = get_log_method(level_string)
    prefix = prefix or ''

    for k, v in logging.get_loggers().items():
        if k and k.startswith(prefix):
            v.logger.setLevel(level)


def get_log_levels(prefix):
    prefix = prefix or ''
    return {k: logging.logging.getLevelName(v.logger.getEffectiveLevel())
            for k, v in logging.get_loggers().items()
            if k and k.startswith(prefix)}


def paths_normcase_equal(path_a, path_b):
    return os.path.normcase(path_a) == os.path.normcase(path_b)


def create_ordereddict(adict):
    """Given a dict, return a sorted OrderedDict."""
    return OrderedDict(sorted(adict.items(),
                              key=operator.itemgetter(0)))


class Semaphore(object):
    """Custom semaphore to workaround eventlet issues with multiprocessing."""
    def __init__(self, limit):
        self.limit = limit
        self.semaphore = multiprocessing.Semaphore(limit)

    def __enter__(self):
        # Eventlet does not work with multiprocessing's Semaphore, so we have
        # to execute it in a native thread to avoid getting blocked when trying
        # to acquire the semaphore.
        return tpool.execute(self.semaphore.__enter__)

    def __exit__(self, *args):
        # Don't use native thread for exit, as it will only add overhead
        return self.semaphore.__exit__(*args)


def semaphore_factory(limit, concurrent_processes):
    """Get a semaphore to limit concurrent operations.

    The semaphore depends on the limit we want to set and the concurrent
    processes that need to be limited.
    """
    # Limit of 0 is no limit, so we won't use a semaphore
    if limit:
        # If we only have 1 process we can use eventlet's Semaphore
        if concurrent_processes == 1:
            return eventlet.Semaphore(limit)
        # Use our own Sempahore for interprocess because eventlet blocks with
        # the standard one
        return Semaphore(limit)
    return contextlib.suppress()


def limit_operations(func):
    """Decorator to limit the number of concurrent operations.

     This method decorator expects to have a _semaphore attribute holding an
     initialized semaphore in the self instance object.

     We can get the appropriate semaphore with the semaphore_factory method.
     """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        with self._semaphore:
            return func(self, *args, **kwargs)
    return wrapper
