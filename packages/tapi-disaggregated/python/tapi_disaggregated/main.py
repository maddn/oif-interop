# -*- mode: python; python-indent: 4 -*-
import ncs
from ncs.application import NanoService
from tapi_disaggregated.ot_tapi import (find_onep, OtTapi, OtTapiDelete)

# pylint: disable=attribute-defined-outside-init
class NanoServiceCallbacks(NanoService):
    def get_device_transceiver(self, sip_uuid):
        sip = self.tapi_context.service_interface_point[sip_uuid]
        if 'OT_CLIENT_PORT' not in sip.name:
            raise Exception(
                'All service-interface-points must be OT client ports')

        (_, node, _) = find_onep(self.topology_context, sip_uuid)
        return (node.name['NAME'].value, sip.name['OT_CLIENT_PORT'].value)

    #pylint: disable=too-many-arguments
    @NanoService.create
    def cb_nano_create(self, tctx, root, service, plan, component, state,
                       proplist, _):
        self.log.info('Service create(service=', service._path, ')')
        self.tapi_context = root.tapi_common__context
        self.topology_context = self.tapi_context.tapi_topology__topology_context

        service_name = service.uuid
        if 'SERVICE_NAME' in service.name:
            service_name = service.name['SERVICE_NAME'].value
        elif 'NAME' in service.name:
            service_name = service.name['NAME'].value

        end_points = iter(service.end_point)

        end_point = next(end_points)
        (a_end_device, a_end_transceiver) = self.get_device_transceiver(
            end_point.service_interface_point.service_interface_point_uuid)

        end_point = next(end_points)
        (z_end_device, z_end_transceiver) = self.get_device_transceiver(
            end_point.service_interface_point.service_interface_point_uuid)

        return [
            ('SERVICE_NAME',        f"'{service_name}'"),
            ('A_END_DEVICE',        a_end_device),
            ('A_END_TRANSCEIVER',   a_end_transceiver),
            ('Z_END_DEVICE',        z_end_device),
            ('Z_END_TRANSCEIVER',   z_end_transceiver)]


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):
    def setup(self):
        # The application class sets up logging for us. It is accessible
        # through 'self.log' and is a ncs.log.Log instance.
        self.log.info('Main RUNNING')

        self.register_nano_service('tapi-connectivity-service-servicepoint',
                                   'td:open-terminals',
                                   'ncs:init',
                                   NanoServiceCallbacks)

        self.register_action('generate-ot-tapi-data', OtTapi)
        self.register_action('delete-ot-tapi-data', OtTapiDelete)

    def teardown(self):
        # When the application is finished (which would happen if NCS went
        # down, packages were reloaded or some error occurred) this teardown
        # method will be called.

        self.log.info('Main FINISHED')
