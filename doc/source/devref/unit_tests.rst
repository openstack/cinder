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

Documenation is left in place for those that still use it.

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


Suppressing logging output when tests fail
------------------------------------------

By default, when one or more unit test fails, all of the data sent to the
logger during the failed tests will appear on standard output, which typically
consists of many lines of texts. The logging output can make it difficult to
identify which specific tests have failed, unless your terminal has a large
scrollback buffer or you have redirected output to a file.

You can suppress the logging output by calling ``run_tests.sh`` with the nose
flag::

    --nologcapture

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

Some of the unit tests make queries against an sqlite database [#f3]_. By
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
to fail or stop completely as a result of Python lockfile issues [#f4]_. You
can get around this by manually setting or updating the following line in
``cinder/tests/conf_fixture.py``::

    CONF['lock_path'].SetDefault('/tmp')

Note that you may use any location (not just ``/tmp``!) as long as it is not
a shared folder.

.. rubric:: Footnotes

.. [#f1] See :doc:`jenkins`.

.. [#f2] See :doc:`development.environment` for more details about the use of
   virtualenv.
