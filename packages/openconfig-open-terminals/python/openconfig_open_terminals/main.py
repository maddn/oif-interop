# -*- mode: python; python-indent: 4 -*-
import threading
import traceback
import time

from openconfig_open_terminals.cache import (
    GetComponentsAction, GetOperationalModesAction,
    GenerateInventoryAction, GenerateOpenConfigCacheAction)
import ncs
from ncs.application import Service
from ncs.dp import Action


CHECK_OPER_STATE_INTERVAL = 30
CHECK_OPER_STATE_TIMEOUT = 300

def get_transceiver_port(device, port_type, transceiver_name):
    inventory_cache = device.openconfig_cache.inventory.chassis
    if not inventory_cache:
        raise Exception(f'No inventory cache found for device {device.name}')

    for chassis in inventory_cache:
        for linecard in chassis.linecards.linecard:
            for port in linecard.ports.port:
                if port.port_type == port_type:
                    transceiver = port[port_type].transceiver
                    if transceiver.name == transceiver_name:
                        return port

    raise Exception(f'Unable to find {port_type} transceiver '
                    f'{transceiver_name} in the inventory cache '
                    f'for device {device.name}')

def get_last_channel(device, client_transceiver_name):
    port = get_transceiver_port(
        device, 'terminal-client', client_transceiver_name)
    logical_channels = port.terminal_client.transceiver.logical_channels.channel

    if logical_channels:
        return logical_channels[logical_channels.keys()[-1]]
    return None

def get_optical_channel(root, device_name, client_transceiver_name):
    device = root.devices.device[device_name]
    component_cache = device.openconfig_cache.components.component
    if not component_cache:
        raise Exception(f'No component cache found for device {device.name}')

    last_channel = get_last_channel(device, client_transceiver_name)
    if last_channel and last_channel.next_channel:
        optical_channel_name = next(iter(last_channel.next_channel)).name
        if optical_channel_name in component_cache and component_cache[
                optical_channel_name].type == 'OPTICAL_CHANNEL':
            return optical_channel_name

    return Exception(f'Unable to find the optical-channel connected to '
                     f'client transceiver {client_transceiver_name} in the '
                     f'inventory cache for device {device.name}')

def get_line_port(root, device_name, optical_channel_name):
    return root.devices.device[
        device_name].openconfig_cache.components.component[
            optical_channel_name].line_port

# ------------------------
# SERVICE CALLBACK EXAMPLE
# ------------------------
class ServiceCallbacks(Service):
    # The create() callback is invoked inside NCS FASTMAP and
    # must always exist.
    @Service.create
    def cb_create(self, tctx, root, service, proplist):
        self.log.info('Service create(service=', service._path, ')')

        a_end_optical_channel = get_optical_channel(
            root, service.a_end.device, service.a_end.client_transceiver)
        service.a_end.line_transceiver = get_line_port(
            root, service.a_end.device, a_end_optical_channel)

        z_end_optical_channel = get_optical_channel(
            root, service.z_end.device, service.z_end.client_transceiver)
        service.z_end.line_transceiver = get_line_port(
            root, service.z_end.device, z_end_optical_channel)

        vars = ncs.template.Variables()
        vars.add('A_END_OPTICAL_CHANNEL', a_end_optical_channel)
        vars.add('Z_END_OPTICAL_CHANNEL', z_end_optical_channel)

        template = ncs.template.Template(service)
        template.apply('openconfig-ot-connectivity-template', vars)


def get_link_state(root, service_end_point):
    device = root.devices.device[service_end_point.device]
    port = get_transceiver_port(
        device, 'terminal-line', service_end_point.line_transceiver)
    index = port.terminal_line.optical_channel.logical_channel.index
    channels = device.live_status.oc_opt_term__terminal_device.logical_channels

    # Stop NSO checking the key exists(RPC fails on device)
    _ = next(iter(channels.channel), None)

    return channels.channel[index].state.link_state

def get_frequency(root, service_end_point):
    device = root.devices.device[service_end_point.device]
    port = get_transceiver_port(
        device, 'terminal-line', service_end_point.line_transceiver)
    optical_channel = port.terminal_line.optical_channel
    return device.live_status.oc_platform__components.component[
        optical_channel.name].optical_channel.state.frequency

# Check the link-state is UP and that the laser is tuned to the correct
# frequency on both line ports
class CheckOperationalStateThread(threading.Thread):
    def __init__(self, log, username, service_name):
        super().__init__()
        self.username = username
        self.service_name = service_name
        self.log = log
        self.modes = []

    def run(self):
        try:
            self.log.info('check-operational-state service name: ',
                          self.service_name)
            elapsed = 0
            state = 'DOWN'
            while state != 'UP' and elapsed <= CHECK_OPER_STATE_TIMEOUT:
                time.sleep(CHECK_OPER_STATE_INTERVAL)
                elapsed += CHECK_OPER_STATE_INTERVAL

                with ncs.maapi.single_read_trans(self.username, 'python') as th:
                    root = ncs.maagic.get_root(th)
                    service = root.ot_connectivity[self.service_name]
                    if get_frequency(root, service.a_end) == service.frequency:
                        if get_frequency(
                                root, service.z_end) == service.frequency:
                            state = get_link_state(root, service.a_end)
                            if state == 'UP':
                                state = get_link_state(root, service.z_end)

            with ncs.maapi.single_write_trans(self.username, 'python') as th:
                root = ncs.maagic.get_root(th)
                service = root.ot_connectivity[self.service_name]
                service.operational_state = state
                th.apply()

        except Exception as err:
            self.log.error(err)
            self.log.error(traceback.format_exc())
            raise

class CheckOperationalStateAction(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        CheckOperationalStateThread(
            self.log, uinfo.username, str(kp[0][0])).start()


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):
    def setup(self):
        # The application class sets up logging for us. It is accessible
        # through 'self.log' and is a ncs.log.Log instance.
        self.log.info('Main RUNNING')

        self.register_service('ot-connectivity-servicepoint', ServiceCallbacks)
        self.register_action('check-ot-connectivity-state',
                             CheckOperationalStateAction)

        self.register_action('get-device-components', GetComponentsAction)
        self.register_action('get-device-operational-modes',
                             GetOperationalModesAction)
        self.register_action('generate-device-inventory',
                             GenerateInventoryAction)
        self.register_action('generate-openconfig-cache',
                             GenerateOpenConfigCacheAction)

        # If we registered any callback(s) above, the Application class
        # took care of creating a daemon (related to the service/action point).

        # When this setup method is finished, all registrations are
        # considered done and the application is 'started'.

    def teardown(self):
        # When the application is finished (which would happen if NCS went
        # down, packages were reloaded or some error occurred) this teardown
        # method will be called.

        self.log.info('Main FINISHED')
