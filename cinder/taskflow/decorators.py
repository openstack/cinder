# -*- coding: utf-8 -*-

# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (C) 2012 Yahoo! Inc. All Rights Reserved.
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

import collections
import functools
import inspect
import types

# These arguments are ones that we will skip when parsing for requirements
# for a function to operate (when used as a task).
AUTO_ARGS = ('self', 'context', 'cls')


def is_decorated(functor):
    if not isinstance(functor, (types.MethodType, types.FunctionType)):
        return False
    return getattr(extract(functor), '__task__', False)


def extract(functor):
    # Extract the underlying functor if its a method since we can not set
    # attributes on instance methods, this is supposedly fixed in python 3
    # and later.
    #
    # TODO(harlowja): add link to this fix.
    assert isinstance(functor, (types.MethodType, types.FunctionType))
    if isinstance(functor, types.MethodType):
        return functor.__func__
    else:
        return functor


def _mark_as_task(functor):
    setattr(functor, '__task__', True)


def _get_wrapped(function):
    """Get the method at the bottom of a stack of decorators."""

    if hasattr(function, '__wrapped__'):
        return getattr(function, '__wrapped__')

    if not hasattr(function, 'func_closure') or not function.func_closure:
        return function

    def _get_wrapped_function(function):
        if not hasattr(function, 'func_closure') or not function.func_closure:
            return None

        for closure in function.func_closure:
            func = closure.cell_contents

            deeper_func = _get_wrapped_function(func)
            if deeper_func:
                return deeper_func
            elif hasattr(closure.cell_contents, '__call__'):
                return closure.cell_contents

    return _get_wrapped_function(function)


def _take_arg(a):
    if a in AUTO_ARGS:
        return False
    # In certain decorator cases it seems like we get the function to be
    # decorated as an argument, we don't want to take that as a real argument.
    if isinstance(a, collections.Callable):
        return False
    return True


def wraps(fn):
    """This will not be needed in python 3.2 or greater which already has this
    built-in to its functools.wraps method.
    """

    def wrapper(f):
        f = functools.wraps(fn)(f)
        f.__wrapped__ = getattr(fn, '__wrapped__', fn)
        return f

    return wrapper


def locked(f):

    @wraps(f)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return f(self, *args, **kwargs)

    return wrapper


def task(*args, **kwargs):
    """Decorates a given function and ensures that all needed attributes of
    that function are set so that the function can be used as a task.
    """

    def decorator(f):
        w_f = extract(f)

        def noop(*args, **kwargs):
            pass

        # Mark as being a task
        _mark_as_task(w_f)

        # By default don't revert this.
        w_f.revert = kwargs.pop('revert_with', noop)

        # Associate a name of this task that is the module + function name.
        w_f.name = "%s.%s" % (f.__module__, f.__name__)

        # Sets the version of the task.
        version = kwargs.pop('version', (1, 0))
        f = _versionize(*version)(f)

        # Attach any requirements this function needs for running.
        requires_what = kwargs.pop('requires', [])
        f = _requires(*requires_what, **kwargs)(f)

        # Attach any optional requirements this function needs for running.
        optional_what = kwargs.pop('optional', [])
        f = _optional(*optional_what, **kwargs)(f)

        # Attach any items this function provides as output
        provides_what = kwargs.pop('provides', [])
        f = _provides(*provides_what, **kwargs)(f)

        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)

        return wrapper

    # This is needed to handle when the decorator has args or the decorator
    # doesn't have args, python is rather weird here...
    if kwargs or not args:
        return decorator
    else:
        if isinstance(args[0], collections.Callable):
            return decorator(args[0])
        else:
            return decorator


def _versionize(major, minor=None):
    """A decorator that marks the wrapped function with a major & minor version
    number.
    """

    if minor is None:
        minor = 0

    def decorator(f):
        w_f = extract(f)
        w_f.version = (major, minor)

        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)

        return wrapper

    return decorator


def _optional(*args, **kwargs):
    """Attaches a set of items that the decorated function would like as input
    to the functions underlying dictionary.
    """

    def decorator(f):
        w_f = extract(f)

        if not hasattr(w_f, 'optional'):
            w_f.optional = set()

        w_f.optional.update([a for a in args if _take_arg(a)])

        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)

        return wrapper

    # This is needed to handle when the decorator has args or the decorator
    # doesn't have args, python is rather weird here...
    if kwargs or not args:
        return decorator
    else:
        if isinstance(args[0], collections.Callable):
            return decorator(args[0])
        else:
            return decorator


def _requires(*args, **kwargs):
    """Attaches a set of items that the decorated function requires as input
    to the functions underlying dictionary.
    """

    def decorator(f):
        w_f = extract(f)

        if not hasattr(w_f, 'requires'):
            w_f.requires = set()

        if kwargs.pop('auto_extract', True):
            inspect_what = _get_wrapped(f)
            f_args = inspect.getargspec(inspect_what).args
            w_f.requires.update([a for a in f_args if _take_arg(a)])

        w_f.requires.update([a for a in args if _take_arg(a)])

        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)

        return wrapper

    # This is needed to handle when the decorator has args or the decorator
    # doesn't have args, python is rather weird here...
    if kwargs or not args:
        return decorator
    else:
        if isinstance(args[0], collections.Callable):
            return decorator(args[0])
        else:
            return decorator


def _provides(*args, **kwargs):
    """Attaches a set of items that the decorated function provides as output
    to the functions underlying dictionary.
    """

    def decorator(f):
        w_f = extract(f)

        if not hasattr(f, 'provides'):
            w_f.provides = set()

        w_f.provides.update([a for a in args if _take_arg(a)])

        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)

        return wrapper

    # This is needed to handle when the decorator has args or the decorator
    # doesn't have args, python is rather weird here...
    if kwargs or not args:
        return decorator
    else:
        if isinstance(args[0], collections.Callable):
            return decorator(args[0])
        else:
            return decorator
