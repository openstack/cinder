.. -*- rst -*-

Messages
========

Lists all, shows, and deletes messages.


Delete message
~~~~~~~~~~~~~~

.. rest_method::  DELETE /v3/{project_id}/messages/{message_id}

Deletes a message.

Normal response codes: 202
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - message_id: message_id


Show message details
~~~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/messages/{message_id}

Shows details for a message.


Normal response codes: 200
Error response codes: badRequest(400), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - message_id: message_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - request_id: request_id
   - links: links_5
   - message_level: message_level
   - event_id: event_id
   - created_at: created_at
   - guaranteed_until: guaranteed_until
   - resource_uuid: resource_uuid
   - id: id_8
   - resource_type: resource_type
   - user_message: user_message

Response Example
----------------

.. literalinclude:: ./samples/messages-show-response.json
   :language: javascript


List messages
~~~~~~~~~~~~~

.. rest_method::  GET /v3/{project_id}/messages

Lists all messages, since v3.31 if non-admin users
specify invalid filters in the url, API will return bad request.


Normal response codes: 200
Error response codes: badRequest(400)


Request
-------

.. rest_parameters:: parameters.yaml

   - project_id: project_id_path
   - sort_key: sort_key
   - sort_dir: sort_dir
   - limit: limit
   - offset: offset
   - marker: marker

Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - request_id: request_id
   - links: links_5
   - message_level: message_level
   - event_id: event_id
   - created_at: created_at
   - guaranteed_until: guaranteed_until
   - resource_uuid: resource_uuid
   - id: id_8
   - resource_type: resource_type
   - user_message: user_message

Response Example
----------------

.. literalinclude:: ./samples/messages-list-response.json
   :language: javascript
