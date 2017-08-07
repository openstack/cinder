User Messages
=============

User messages are a way to inform users about the state of asynchronous
operations. One example would be notifying the user of why a volume
provisioning request failed. These messages can be requested via the
/messages API. All user visible messages must be defined in the permitted
messages module in order to prevent sharing sensitive information with users.


Example message generation::

 from cinder import context
 from cinder.message import api as message_api
 from cinder.message import defined_messages
 from cinder.message import resource_types

 self.message_api = message_api.API()

 context = context.RequestContext()
 project_id = '6c430ede-9476-4128-8838-8d3929ced223'
 volume_id = 'f292cc0c-54a7-4b3b-8174-d2ff82d87008'

 self.message_api.create(
     context,
     defined_messages.EventIds.UNABLE_TO_ALLOCATE,
     project_id,
     resource_type=resource_types.VOLUME,
     resource_uuid=volume_id)

Will produce the following::

 GET /v3/6c430ede-9476-4128-8838-8d3929ced223/messages
 {
   "messages": [
     {
      "id": "5429fffa-5c76-4d68-a671-37a8e24f37cf",
      "event_id": "000002",
      "user_message": "No storage could be allocated for this volume request.",
      "message_level": "ERROR",
      "resource_type": "VOLUME",
      "resource_uuid": "f292cc0c-54a7-4b3b-8174-d2ff82d87008",
      "created_at": 2015-08-27T09:49:58-05:00,
      "guaranteed_until": 2015-09-27T09:49:58-05:00,
      "request_id": "req-936666d2-4c8f-4e41-9ac9-237b43f8b848",
     }
   ]
 }



The Message API Module
----------------------

.. automodule:: cinder.message.api
    :noindex:
    :members:
    :undoc-members:

The Message Field Module
------------------------

.. automodule:: cinder.message.message_field
    :noindex:

The Permitted Messages Module
-----------------------------

.. automodule:: cinder.message.defined_messages
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:
