API Microversions
=================

Background
----------

Cinder uses a framework we called 'API Microversions' for allowing changes
to the API while preserving backward compatibility. The basic idea is
that a user has to explicitly ask for their request to be treated with
a particular version of the API. So breaking changes can be added to
the API without breaking users who don't specifically ask for it. This
is done with an HTTP header ``OpenStack-API-Version`` which
is a monotonically increasing semantic version number starting from
``3.0``.

Each OpenStack service that uses microversions will share this header, so
the Volume service will need to prefix the semantic version number with the
word ``volume``::

  OpenStack-API-Version: volume 3.0

If a user makes a request without specifying a version, they will get
the ``DEFAULT_API_VERSION`` as defined in
``cinder/api/openstack/api_version_request.py``. This value is currently ``3.0``
and is expected to remain so for quite a long time.

The Nova project was the first to implement microversions. For full
details please read Nova's `Kilo spec for microversions
<http://git.openstack.org/cgit/openstack/nova-specs/tree/specs/kilo/implemented/api-microversions.rst>`_

When do I need a new Microversion?
----------------------------------

A microversion is needed when the contract to the user is
changed. The user contract covers many kinds of information such as:

- the Request

  - the list of resource URLs which exist on the server

    Example: adding a new shares/{ID}/foo which didn't exist in a
    previous version of the code

  - the list of query parameters that are valid on URLs

    Example: adding a new parameter ``is_yellow`` servers/{ID}?is_yellow=True

  - the list of query parameter values for non free form fields

    Example: parameter filter_by takes a small set of constants/enums "A",
    "B", "C". Adding support for new enum "D".

  - new headers accepted on a request

- the Response

  - the list of attributes and data structures returned

    Example: adding a new attribute 'locked': True/False to the output
    of shares/{ID}

  - the allowed values of non free form fields

    Example: adding a new allowed ``status`` to shares/{ID}

  - the list of status codes allowed for a particular request

    Example: an API previously could return 200, 400, 403, 404 and the
    change would make the API now also be allowed to return 409.

  - changing a status code on a particular response

    Example: changing the return code of an API from 501 to 400.

  - new headers returned on a response

The following flow chart attempts to walk through the process of "do
we need a microversion".


.. graphviz::

   digraph states {

    label="Do I need a microversion?"

    silent_fail[shape="diamond", style="", label="Did we silently
   fail to do what is asked?"];
    ret_500[shape="diamond", style="", label="Did we return a 500
   before?"];
    new_error[shape="diamond", style="", label="Are we changing what
    status code is returned?"];
    new_attr[shape="diamond", style="", label="Did we add or remove an
    attribute to a payload?"];
    new_param[shape="diamond", style="", label="Did we add or remove
    an accepted query string parameter or value?"];
    new_resource[shape="diamond", style="", label="Did we add or remove a
   resource URL?"];


   no[shape="box", style=rounded, label="No microversion needed"];
   yes[shape="box", style=rounded, label="Yes, you need a microversion"];
   no2[shape="box", style=rounded, label="No microversion needed, it's
   a bug"];

   silent_fail -> ret_500[label="no"];
   silent_fail -> no2[label="yes"];

    ret_500 -> no2[label="yes [1]"];
    ret_500 -> new_error[label="no"];

    new_error -> new_attr[label="no"];
    new_error -> yes[label="yes"];

    new_attr -> new_param[label="no"];
    new_attr -> yes[label="yes"];

    new_param -> new_resource[label="no"];
    new_param -> yes[label="yes"];

    new_resource -> no[label="no"];
    new_resource -> yes[label="yes"];

   {rank=same; yes new_attr}
   {rank=same; no2 ret_500}
   {rank=min; silent_fail}
   }


**Footnotes**

[1] - When fixing 500 errors that previously caused stack traces, try
to map the new error into the existing set of errors that API call
could previously return (400 if nothing else is appropriate). Changing
the set of allowed status codes from a request is changing the
contract, and should be part of a microversion.

The reason why we are so strict on contract is that we'd like
application writers to be able to know, for sure, what the contract is
at every microversion in Cinder. If they do not, they will need to write
conditional code in their application to handle ambiguities.

When in doubt, consider application authors. If it would work with no
client side changes on both Cinder versions, you probably don't need a
microversion. If, on the other hand, there is any ambiguity, a
microversion is probably needed.


In Code
-------

In ``cinder/api/openstack/wsgi.py`` we define an ``@api_version`` decorator
which is intended to be used on top-level Controller methods. It is
not appropriate for lower-level methods. Some examples:

Adding a new API method
~~~~~~~~~~~~~~~~~~~~~~~

In the controller class::

    @wsgi.Controller.api_version("3.4")
    def my_api_method(self, req, id):
        ....

This method would only be available if the caller had specified an
``OpenStack-API-Version`` of >= ``3.4``. If they had specified a
lower version (or not specified it and received the default of ``3.1``)
the server would respond with ``HTTP/404``.

Removing an API method
~~~~~~~~~~~~~~~~~~~~~~

In the controller class::

    @wsgi.Controller.api_version("3.1", "3.4")
    def my_api_method(self, req, id):
        ....

This method would only be available if the caller had specified an
``OpenStack-API-Version`` of <= ``3.4``, and >= ``3.1``. If ``3.5`` or later
is specified or if ``3.0`` or earlier (/v2 or /v1 endpoint), the server will
respond with ``HTTP/404``

Changing a method's behaviour
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In the controller class::

    @wsgi.Controller.api_version("3.1", "3.3")
    def my_api_method(self, req, id):
        .... method_1 ...

    @my_api_method.api_version("3.4")
    def my_api_method(self, req, id):
        .... method_2 ...

If a caller specified ``3.1``, ``3.2`` or ``3.3`` (or received the
default of ``3.1``) they would see the result from ``method_1``,
``3.4`` or later ``method_2``.

We could use ``wsgi.Controller.api_version`` decorator on the second
``my_api_method`` as well, but then we would have to add ``# noqa`` to that
line to avoid failing flake8's ``F811`` rule.  So the recommended approach is
to use the ``api_version`` decorator from the first method that is defined, as
illustrated by the example above, and then use ``my_api_method`` decorator for
subsequent api versions of the same method.

The two methods may be different in any kind of semantics (schema validation,
return values, response codes, etc.).

A method with only small changes between versions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A method may have only small changes between microversions, in which
case you can decorate a private method::

    @wsgi.Controller.api_version("3.1", "3.4")
    def _version_specific_func(self, req, arg1):
        pass

    @_version_specific_func.api_version(min_ver="3.5")
    def _version_specific_func(self, req, arg1):
        pass

    def show(self, req, id):
        .... common stuff ....
        self._version_specific_func(req, "foo")
        .... common stuff ....

When not using decorators
~~~~~~~~~~~~~~~~~~~~~~~~~

When you don't want to use the ``@api_version`` decorator on a method
or you want to change behaviour within a method (say it leads to
simpler or simply a lot less code) you can directly test for the
requested version with a method as long as you have access to the api
request object (commonly called ``req``). Every API method has an
api_version_request object attached to the req object and that can be
used to modify behaviour based on its value::

    def index(self, req):
        <common code>

        req_version = req.api_version_request
        if req_version.matches("3.1", "3.5"):
            ....stuff....
        elif req_version.matches("3.6", "3.10"):
            ....other stuff....
        elif req_version > api_version_request.APIVersionRequest("3.10"):
            ....more stuff.....

        <common code>

The first argument to the matches method is the minimum acceptable version
and the second is maximum acceptable version. A specified version can be null::

    null_version = APIVersionRequest()

If the minimum version specified is null then there is no restriction on
the minimum version, and likewise if the maximum version is null there
is no restriction the maximum version. Alternatively a one sided comparison
can be used as in the example above.

Other necessary changes
-----------------------

If you are adding a patch which adds a new microversion, it is
necessary to add changes to other places which describe your change:

* Update ``REST_API_VERSION_HISTORY`` in
  ``cinder/api/openstack/api_version_request.py``

* Update ``_MAX_API_VERSION`` in
  ``cinder/api/openstack/api_version_request.py``

* Add a verbose description to
  ``cinder/api/openstack/rest_api_version_history.rst``.  There should
  be enough information that it could be used by the docs team for
  release notes.

* Update the expected versions in affected tests.

Allocating a microversion
-------------------------

If you are adding a patch which adds a new microversion, it is
necessary to allocate the next microversion number. Except under
extremely unusual circumstances and this would have been mentioned in
the blueprint for the change, the minor number of ``_MAX_API_VERSION``
will be incremented. This will also be the new microversion number for
the API change.

It is possible that multiple microversion patches would be proposed in
parallel and the microversions would conflict between patches.  This
will cause a merge conflict. We don't reserve a microversion for each
patch in advance as we don't know the final merge order. Developers
may need over time to rebase their patch calculating a new version
number as above based on the updated value of ``_MAX_API_VERSION``.

Testing Microversioned API Methods
----------------------------------

Unit tests for microversions should be put in cinder/tests/unit/api/v3/ .
Since all existing functionality is tested in cinder/tests/unit/api/v2,
these unit tests are not replicated in .../v3, and only new functionality
needs to be place in the .../v3/directory.

Testing a microversioned API method is very similar to a normal controller
method test, you just need to add the ``OpenStack-API-Version``
header, for example::

    req = fakes.HTTPRequest.blank('/testable/url/endpoint')
    req.headers['OpenStack-API-Version'] = 'volume 3.6'
    req.api_version_request = api_version.APIVersionRequest('3.6')

    controller = controller.TestableController()

    res = controller.index(req)
    ... assertions about the response ...

