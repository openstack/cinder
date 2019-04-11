User Messages
=============

General information
~~~~~~~~~~~~~~~~~~~

User messages are a way to inform users about the state of asynchronous
operations. One example would be notifying the user of why a volume
provisioning request failed. End users can request these messages via the
Volume v3 REST API under the ``/messages`` resource.  The REST API allows
only GET and DELETE verbs for this resource.

Internally, you use the ``cinder.message.api`` to work with messages.  In
order to prevent leakage of sensitive information or breaking the volume
service abstraction layer, free-form messages are *not* allowed.  Instead, all
messages must be defined using a combination of pre-defined fields in the
``cinder.message.message_field`` module.

The message ultimately displayed to end users is combined from an ``Action``
field and a ``Detail`` field.

* The ``Action`` field describes what was taking place when the message
  was created, for example, ``Action.COPY_IMAGE_TO_VOLUME``.

* The ``Detail`` field is used to provide more information, for example,
  ``Detail.NOT_ENOUGH_SPACE_FOR_IMAGE`` or ``Detail.QUOTA_EXCEED``.

Example
~~~~~~~

Example message generation::

 from cinder import context
 from cinder.message import api as message_api
 from cinder.message import message_field

 self.message_api = message_api.API()

 context = context.RequestContext()
 volume_id = 'f292cc0c-54a7-4b3b-8174-d2ff82d87008'

 self.message_api.create(
     context,
     message_field.Action.UNMANAGE_VOLUME,
     resource_uuid=volume_id,
     detail=message_field.Detail.UNMANAGE_ENC_NOT_SUPPORTED)

Will produce roughly the following::

 GET /v3/6c430ede-9476-4128-8838-8d3929ced223/messages
 {
   "messages": [
     {
      "id": "5429fffa-5c76-4d68-a671-37a8e24f37cf",
      "event_id": "VOLUME_VOLUME_006_008",
      "user_message": "unmanage volume: Unmanaging encrypted volumes is not supported.",
      "message_level": "ERROR",
      "resource_type": "VOLUME",
      "resource_uuid": "f292cc0c-54a7-4b3b-8174-d2ff82d87008",
      "created_at": 2018-08-27T09:49:58-05:00,
      "guaranteed_until": 2018-09-27T09:49:58-05:00,
      "request_id": "req-936666d2-4c8f-4e41-9ac9-237b43f8b848",
     }
   ]
 }

Adding user messages
~~~~~~~~~~~~~~~~~~~~

If you are creating a message in the code but find that the predefined fields
are insufficient, just add what you need to ``cinder.message.message_field``.
The key thing to keep in mind is that all defined fields should be appropriate
for any API user to see and not contain any sensitive information. A good
rule-of-thumb is to be very general in error messages unless the issue is due
to a bad user action, then be specific.

As a convenience to developers, the ``Detail`` class contains a
``EXCEPTION_DETAIL_MAPPINGS`` dict.  This maps ``Detail`` fields to particular
Cinder exceptions, and allows you to create messages in a context where you've
caught an Exception that could be any of several possibilities.  Instead of
having to sort through them where you've caught the exception, you can call
``message_api.create`` and pass it both the exception and a general detail
field like ``Detail.SOMETHING_BAD_HAPPENED`` (that's not a real field, but
you get the idea).  If the passed exception is in the mapping, the resulting
message will have the mapped ``Detail`` field instead of the generic one.

Usage patterns
~~~~~~~~~~~~~~

These are taken from the Cinder code.  The exact code may have changed
by the time you read this, but the general idea should hold.

No exception in context
-----------------------

From cinder/compute/nova.py::

    def extend_volume(self, context, server_ids, volume_id):
        api_version = '2.51'
        events = [self._get_volume_extended_event(server_id, volume_id)
                  for server_id in server_ids]
        result = self._send_events(context, events, api_version=api_version)
        if not result:
            self.message_api.create(
                context,
                message_field.Action.EXTEND_VOLUME,
                resource_uuid=volume_id,
                detail=message_field.Detail.NOTIFY_COMPUTE_SERVICE_FAILED)
        return result

* You must always pass the context object and an action.
* We're working with an existing volume, so pass its ID as the
  ``resource_uuid``.
* You need to fill in some detail, or else the code will supply an
  ``UNKNOWN_ERROR``, which isn't very helpful.

Cinder exception in context
---------------------------

From cinder/scheduler/manager.py::

        except exception.NoValidBackend as ex:
            QUOTAS.rollback(context, reservations,
                            project_id=volume.project_id)
            _extend_volume_set_error(self, context, ex, request_spec)
            self.message_api.create(
                context,
                message_field.Action.EXTEND_VOLUME,
                resource_uuid=volume.id,
                exception=ex)

* You must always pass the context object and an action.
* Since we have it available, pass the volume ID as the resource_uuid.
* It's a Cinder exception.  Check to see if it's in the mapping.

  * If it's there, we can pass it, and the detail will be supplied
    by the code.
  * It it's not, consider adding it and mapping it to an existing
    ``Detail`` field.  If there's no current ``Detail`` field for that
    exception, go ahead and add that, too.
  * On the other hand, maybe it's in the mapping, but you have more
    information in this code context than is available in the mapped
    ``Detail`` field.  In that case, you may want to use a different
    ``Detail`` field (creating it if necessary).
  * Remember, if you pass *both* a mapped exception *and* a detail, the
    passed detail will be ignored and the mapped ``Detail`` field will be
    used instead.

General Exception in context
----------------------------

Not passing the Exception to message_api.create()
+++++++++++++++++++++++++++++++++++++++++++++++++

From cinder/volume/manager.py::

        try:
            self.driver.extend_volume(volume, new_size)
        except exception.TargetUpdateFailed:
            # We just want to log this but continue on with quota commit
            LOG.warning('Volume extended but failed to update target.')
        except Exception:
            LOG.exception("Extend volume failed.",
                          resource=volume)
            self.message_api.create(
                context,
                message_field.Action.EXTEND_VOLUME,
                resource_uuid=volume.id,
                detail=message_field.Detail.DRIVER_FAILED_EXTEND)

* Pass the context object and an action; pass a ``resource_uuid`` since we
  have it.
* We're not passing the exception, so the ``detail`` we pass is guaranteed
  to be used.

Passing the Exception to message_api.create()
+++++++++++++++++++++++++++++++++++++++++++++

From cinder/volume/manager.py::

        try:
            if volume_metadata.get('readonly') == 'True' and mode != 'ro':
                raise exception.InvalidVolumeAttachMode(mode=mode,
                                                        volume_id=volume.id)
            utils.require_driver_initialized(self.driver)

            LOG.info('Attaching volume %(volume_id)s to instance '
                     '%(instance)s at mountpoint %(mount)s on host '
                     '%(host)s.',
                     {'volume_id': volume_id, 'instance': instance_uuid,
                      'mount': mountpoint, 'host': host_name_sanitized},
                     resource=volume)
            self.driver.attach_volume(context,
                                      volume,
                                      instance_uuid,
                                      host_name_sanitized,
                                      mountpoint)
        except Exception as excep:
            with excutils.save_and_reraise_exception():
                self.message_api.create(
                    context,
                    message_field.Action.ATTACH_VOLUME,
                    resource_uuid=volume_id,
                    exception=excep)
                attachment.attach_status = (
                    fields.VolumeAttachStatus.ERROR_ATTACHING)
                attachment.save()

* Pass the context object and an action; pass a resource_uuid since we
  have it.
* We're passing an exception, which could be a Cinder
  ``InvalidVolumeAttachMode``, which is in the mapping.  In that case, the
  mapped ``Detail`` will be used;
  otherwise, the code will supply a ``Detail.UNKNOWN_ERROR``.

  This is appropriate if we really have no idea what happened.  If it's
  possible to provide more information, we can pass a different, generic
  ``Detail`` field (creating it if necessary).  The passed detail would be
  used for any exception that's *not* in the mapping.  If it's a mapped
  exception, then the mapped ``Detail`` field will be used.

Module documentation
~~~~~~~~~~~~~~~~~~~~

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

The Defined Messages Module
---------------------------

This module is DEPRECATED and is currently only used by
``cinder.api.v3.messages`` to handle pre-Pike message database objects.
(Editorial comment:: With the default ``message_ttl`` of 2592000 seconds
(30 days), it's probably safe to remove this module during the Train
development cycle.)

.. automodule:: cinder.message.defined_messages
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:
