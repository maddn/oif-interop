# -*- mode: python; python-indent: 4 -*-
import uuid

from tapi_ols.inventory import (
    SipSummary, TopologySummary, ConnectivitySummary,
    ConnectivityServiceConnections, EquipmentSummary)
from tapi_ols.event_stream import (TapiSubscribe, ClearNotifications)

import ncs
from ncs.application import Service
from ncs.cdb import OperSubscriber
from ncs.dp import Action
_ncs = __import__('_ncs') # pylint: disable=invalid-name


class ServiceCallbacks(Service):
    # The create() callback is invoked inside NCS FASTMAP and
    # must always exist.
    @Service.create
    def cb_create(self, tctx, root, service, proplist):
        self.log.info('Service create(service=', service._path, ')')
        service_uuid = None

        for (key, value) in proplist:
            if key == 'uuid':
                service_uuid = value
                self.log.info("UUID found: %s" % value)

        if service_uuid is None:
            service_uuid = str(uuid.uuid4())
            proplist.append(('uuid', service_uuid))
            self.log.info('Created UUID = ' + service_uuid)

        service.uuid = service_uuid

        template = ncs.template.Template(service)
        template.apply('tapi-connectivity-service-template', None)

        return proplist


def set_service_operational_state(service_name, operational_state):
    with ncs.maapi.single_write_trans('admin', 'python',
                                      db=_ncs.OPERATIONAL) as th:
        root = ncs.maagic.get_root(th)
        service = root.ols_connectivity[service_name]
        service.operational_state = operational_state
        th.apply()

class NotificationCdbSubscriber(OperSubscriber):
    #pylint: disable=no-self-use
    #pylint: disable=unused-argument

    def init(self):
        self.register('/ncs:devices/ncs:device/tapi-ols:tapi-context'
                      '/notifications/received/notification')

    def pre_iterate(self):
        return []

    def iterate(self, keypath, op, oldval, newval, state):
        if op is ncs.MOP_CREATED:
            state.append(str(keypath))
        return ncs.ITER_CONTINUE

    def post_iterate(self, state):
        for notification in state:
            self.handle_notification(notification)

    def should_post_iterate(self, state):
        return state != []

    def handle_notification(self, notification_path):
        with ncs.maapi.single_read_trans('admin', 'python') as th:
            root = ncs.maagic.get_root(th)
            notification = ncs.maagic.get_node(th, notification_path)

            if notification.target_object_type == 'CONNECTIVITY_SERVICE':
                service_uuid = notification.target_object_identifier[-36:]
                for service in root.ols_connectivity:
                    if service.uuid == service_uuid:
                        self.log.info('Received notification for service uuid ',
                                      service_uuid)
                        for change in notification.changed_attributes:
                            if change.value_name == 'operational-state':
                                set_service_operational_state(
                                    service.name, change.new_value)

class SetOperationalState(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        set_service_operational_state(str(kp[0][0]), input.state)


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):

    #pylint: disable=attribute-defined-outside-init
    def setup(self):
        # The application class sets up logging for us. It is accessible
        # through 'self.log' and is a ncs.log.Log instance.
        self.log.info('Main RUNNING')

        self.register_service('ols-connectivity-servicepoint', ServiceCallbacks)

        self.register_action('get-topology-summary', TopologySummary)
        self.register_action('get-sip-summary', SipSummary)
        self.register_action('get-connectivity-summary', ConnectivitySummary)
        self.register_action('get-equipment-summary', EquipmentSummary)
        self.register_action('get-connectivity-service-connections',
                             ConnectivityServiceConnections)

        self.register_action('subscribe-tapi-notifications', TapiSubscribe)
        self.register_action('clear-tapi-notifications', ClearNotifications)
        self.register_action('set-service-operational-state', SetOperationalState)

        self.sub = NotificationCdbSubscriber(app=self)
        self.sub.start()


    def teardown(self):
        # When the application is finished (which would happen if NCS went
        # down, packages were reloaded or some error occurred) this teardown
        # method will be called.

        self.sub.stop()
        self.log.info('Main FINISHED')
