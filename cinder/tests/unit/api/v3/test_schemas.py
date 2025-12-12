# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from cinder.api.v3 import router
from cinder.tests.unit import test


class SchemaTest(test.TestCase):

    def setUp(self):
        super().setUp()
        self.router = router.APIRouter()

    def test_schemas(self):
        missing_schemas = set()

        for route in self.router.map.matchlist:
            if 'controller' not in route.defaults:
                continue

            controller = route.defaults['controller']

            # NOTE: This is effectively a reimplementation of
            # 'routes.route.Route.make_full_route' that uses OpenAPI-compatible
            # template strings instead of regexes for paramters
            path = ""
            for part in route.routelist:
                if isinstance(part, dict):
                    path += "{" + part["name"] + "}"
                else:
                    path += part

            method = (
                route.conditions.get("method", "GET")[0]
                if route.conditions
                else "GET"
            )
            action = route.defaults["action"]

            if path.endswith('/action'):
                # all actions should use POST
                assert method == 'POST'

                wsgi_actions = [
                    (k, v, controller.controller) for k, v in
                    controller.controller.wsgi_actions.items()
                ]
                for ext_controller in controller.extension_controllers:
                    wsgi_actions += [
                        (k, v, ext_controller) for k, v in
                        ext_controller.wsgi_actions.items()
                    ]

                for (
                    wsgi_action, wsgi_method, action_controller
                ) in wsgi_actions:
                    # FIXME: The VolumeTypesManageController._delete method is
                    # being mapped as two different APIs - 'DELETE /types/{id}'
                    # and 'POST /types/{id}/action (delete)' (along with the
                    # project ID-prefixed variants) - but only the former of
                    # these is intended and the latter results in a HTTP 500 if
                    # you try to use it. We're skipping it here but we should
                    # really stop generating the mapping.
                    if wsgi_action == 'delete' and path in (
                        '/types/{id}/action',
                        '/{project_id}/types/{id}/action',
                    ):
                        continue

                    func = controller.wsgi_actions[wsgi_action]

                    if hasattr(action_controller, 'versioned_methods'):
                        if wsgi_method in action_controller.versioned_methods:
                            # currently all our actions are unversioned and if
                            # this changes then we need to fix this
                            funcs = action_controller.versioned_methods[
                                wsgi_method
                            ]
                            assert len(funcs) == 1
                            func = funcs[0].func

                    if not hasattr(func, '_request_schema'):
                        missing_schemas.add(func.__qualname__)
            else:
                # body validation
                versioned_methods = getattr(
                    controller.controller, 'versioned_methods', {}
                )
                if action in versioned_methods:
                    # versioned method
                    for versioned_method in sorted(
                        versioned_methods[action],
                        key=lambda v: v.start_version
                    ):
                        func = versioned_method.func

                        if method in ("POST", "PUT", "PATCH"):
                            if not hasattr(func, '_request_schema'):
                                missing_schemas.add(func.__qualname__)
                else:
                    if not hasattr(controller.controller, action):
                        # these are almost certainly because of use of
                        # routes.mapper.Mapper.resource, which we should remove
                        continue

                    # unversioned method
                    func = getattr(controller.controller, action)
                    if method in ("POST", "PUT", "PATCH"):
                        if not hasattr(func, '_request_schema'):
                            missing_schemas.add(func.__qualname__)

        if missing_schemas:
            raise test.TestingException(
                f"Found API resources without schemas: "
                f"{sorted(missing_schemas)}"
            )
