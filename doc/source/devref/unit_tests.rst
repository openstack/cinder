Unit Tests
==========

Cinder contains a suite of unit tests, in the cinder/tests/unit directory.

Any proposed code change will be automatically rejected by the OpenStack
Jenkins server [#f1]_ if the change causes unit test failures.

Running the tests
-----------------
There are a number of ways to run unit tests currently, and there's a combination
of frameworks used depending on what commands you use.  The preferred method
is to use tox, which calls ostestr via the tox.ini file.  To run all tests simply run::

    tox

This will create a virtual environment, load all the packages from test-requirements.txt
and run all unit tests as well as run flake8 and hacking checks against the code.

Note that you can inspect the tox.ini file to get more details on the available options
and what the test run does by default.

Running a subset of tests using tox
-----------------------------------
One common activity is to just run a single test, you can do this with tox simply by
specifying to just run py27 or py34 tests against a single test::

    tox -epy27 -- -n cinder.tests.unit.test_volume.AvailabilityZoneTestCase.test_list_availability_zones_cached

Or all tests in the test_volume.py file::

    tox -epy27 -- -n cinder.tests.unit.test_volume

For more information on these options and how to run tests, please see the `ostestr
documentation <http://docs.openstack.org/developer/os-testr/>`_.

Run tests wrapper script
------------------------

In addition you can also use the wrapper script run_tests.sh by simply executing::

    ./run_tests.sh

This script is a wrapper around the testr testrunner and the flake8 checker. Note that
there has been talk around deprecating this wrapper and this method of testing, it's currently
available still but it may be good to get used to using tox or even ostestr directly.

Documentation is left in place for those that still use it.

Flags
-----

The ``run_tests.sh`` script supports several flags. You can view a list of
flags by doing::

    run_tests.sh -h

This will show the following help information::

    Usage: ./run_tests.sh [OPTION]...
    Run Cinder's test suite(s)

      -V, --virtual-env        Always use virtualenv.  Install automatically if not present
      -N, --no-virtual-env     Don't use virtualenv.  Run tests in local environment
      -s, --no-site-packages   Isolate the virtualenv from the global Python environment
      -r, --recreate-db        Recreate the test database (deprecated, as this is now the default).
      -n, --no-recreate-db     Don't recreate the test database.
      -x, --stop               Stop running tests after the first error or failure.
      -f, --force              Force a clean re-build of the virtual environment. Useful when dependencies have been added.
      -p, --pep8               Just run pep8
      -P, --no-pep8            Don't run pep8
      -c, --coverage           Generate coverage report
      -h, --help               Print this usage message
      --hide-elapsed           Don't print the elapsed time for each test along with slow test list

Because ``run_tests.sh`` is a wrapper around testr, it also accepts the same
flags as testr. See the `testr documentation`_ for details about
these additional flags.

.. _testr documentation: https://testrepository.readthedocs.org/en/latest/
.. _nose options documentation: http://readthedocs.org/docs/nose/en/latest/usage.html#options

Running a subset of tests
-------------------------

Instead of running all tests, you can specify an individual directory, file,
class, or method that contains test code.

To run the tests in the ``cinder/tests/scheduler`` directory::

    ./run_tests.sh scheduler

To run the tests in the ``cinder/tests/test_libvirt.py`` file::

    ./run_tests.sh test_libvirt

To run the tests in the `HostStateTestCase` class in
``cinder/tests/test_libvirt.py``::

    ./run_tests.sh test_libvirt.HostStateTestCase

To run the `ToPrimitiveTestCase.test_dict` test method in
``cinder/tests/test_utils.py``::

    ./run_tests.sh test_utils.ToPrimitiveTestCase.test_dict


Virtualenv
----------

By default, the tests use the Python packages installed inside a
virtualenv [#f2]_. (This is equivalent to using the ``-V, --virtualenv`` flag).
If the virtualenv does not exist, it will be created the first time the tests are run.

If you wish to recreate the virtualenv, call ``run_tests.sh`` with the flag::

    -f, --force

Recreating the virtualenv is useful if the package dependencies have changed
since the virtualenv was last created. If the ``requirements.txt`` or
``tools/install_venv.py`` files have changed, it's a good idea to recreate the
virtualenv.

By default, the unit tests will see both the packages in the virtualenv and
the packages that have been installed in the Python global environment. In
some cases, the packages in the Python global environment may cause a conflict
with the packages in the virtualenv. If this occurs, you can isolate the
virtualenv from the global environment by using the flag::

    -s, --no-site packages

If you do not wish to use a virtualenv at all, use the flag::

    -N, --no-virtual-env

Database
--------

Some of the unit tests make queries against an sqlite database. By
default, the test database (``tests.sqlite``) is deleted and recreated each
time ``run_tests.sh`` is invoked (This is equivalent to using the
``-r, --recreate-db`` flag). To reduce testing time if a database already
exists it can be reused by using the flag::

    -n, --no-recreate-db

Reusing an existing database may cause tests to fail if the schema has
changed. If any files in the ``cinder/db/sqlalchemy`` have changed, it's a good
idea to recreate the test database.

Gotchas
-------

**Running Tests from Shared Folders**

If you are running the unit tests from a shared folder, you may see tests start
to fail or stop completely as a result of Python lockfile issues. You
can get around this by manually setting or updating the following line in
``cinder/tests/conf_fixture.py``::

    CONF['lock_path'].SetDefault('/tmp')

Note that you may use any location (not just ``/tmp``!) as long as it is not
a shared folder.

.. rubric:: Footnotes

.. [#f1] See :doc:`jenkins`.

.. [#f2] See :doc:`development.environment` for more details about the use of
   virtualenv.

**Running py34 tests**

You will need to install:
python3-dev
in order to get py34 tests to run. If you do not have this, you will get the following::

	netifaces.c:1:20: fatal error: Python.h: No such file or directory
	     #include <Python.h>
				^
	    compilation terminated.
	    error: command 'x86_64-linux-gnu-gcc' failed with exit status 1

	    ----------------------------------------
        <snip>
	ERROR: could not install deps [-r/opt/stack/cinder/test-requirements.txt,
        oslo.versionedobjects[fixtures]]; v = InvocationError('/opt/stack/cinder/
        .tox/py34/bin/pip install -r/opt/stack/cinder/test-requirements.txt
         oslo.versionedobjects[fixtures] (see /opt/stack/cinder/.tox/py34/log/py34-1.log)', 1)
	_______________________________________________________________ summary _______________________________________________________________
	ERROR:   py34: could not install deps [-r/opt/stack/cinder/test-requirements.txt,
        oslo.versionedobjects[fixtures]]; v = InvocationError('/opt/stack/cinder/
        .tox/py34/bin/pip install -r/opt/stack/cinder/test-requirements.txt
        oslo.versionedobjects[fixtures] (see /opt/stack/cinder/.tox/py34/log/py34-1.log)', 1)

To Fix:

- On Ubuntu/Debian::

    sudo apt-get install python3-dev

- On Fedora 21/RHEL7/CentOS7::

    sudo yum install python3-devel

- On Fedora 22 and higher::

    sudo dnf install python3-devel
