..
      Copyright 2010-2011 OpenStack Foundation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Adding a Method to the OpenStack API
====================================

The interface is a mostly RESTful API. REST stands for Representational State Transfer and provides an architecture "style" for distributed systems using HTTP for transport. Figure out a way to express your request and response in terms of resources that are being created, modified, read, or destroyed.

Routing
-------

To map URLs to controllers+actions, OpenStack uses the Routes package, a clone of Rails routes for Python implementations. See http://routes.groovie.org/ for more information.

URLs are mapped to "action" methods on "controller" classes in ``cinder/api/openstack/__init__/ApiRouter.__init__`` .

See http://routes.groovie.org/manual.html for all syntax, but you'll probably just need these two:
   - mapper.connect() lets you map a single URL to a single action on a controller.
   - mapper.resource() connects many standard URLs to actions on a controller.

Controllers and actions
-----------------------

Controllers live in ``cinder/api/openstack``, and inherit from cinder.wsgi.Controller.

See ``cinder/api/v2/volumes.py`` for an example.

Action methods take parameters that are sucked out of the URL by mapper.connect() or .resource().  The first two parameters are self and the WebOb request, from which you can get the req.environ, req.body, req.headers, etc.

Serialization
-------------

Actions return a dictionary, and wsgi.Controller serializes that to JSON or XML based on the request's content-type.

Errors
------

There will be occasions when you will want to return a REST error response to
the caller and there are multiple valid ways to do this:

- If you are at the controller level you can use a ``faults.Fault`` instance to
  indicate the error.  You can either return the ``Fault`` instance as the
  result of the action, or raise it, depending on what's more convenient:
  ``raise faults.Fault(webob.exc.HTTPBadRequest(explanation=msg))``.

- If you are raising an exception our WSGI middleware exception handler is
  smart enough to recognize webob exceptions as well, so you don't really need
  to wrap the exceptions in a ``Fault`` class and you can just let the
  middleware add it for you:
  ``raise webob.exc.HTTPBadRequest(explanation=msg)``.

- While most errors require an explicit webob exception there are some Cinder
  exceptions (``NotFound`` and ``Invalid``) that are so common that they are
  directly handled by the middleware and don't need us to convert them, we can
  just raise them at any point in the API service and they will return the
  appropriate REST error to the caller.  So any ``NotFound`` exception, or
  child class, will return a 404 error, and any ``Invalid`` exception, or
  child class, will return a 400 error.
