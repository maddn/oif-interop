# -*- mode: python; python-indent: 4 -*-
import uuid

import ncs
from ncs.dp import Action

PROTOCOL_MAP = {
    'oc-opt-types:PROT_1GE':        'tapi-dsr:DIGITAL_SIGNAL_TYPE_GigE',
    'oc-opt-types:PROT_10GE_LAN':   'tapi-dsr:DIGITAL_SIGNAL_TYPE_10_GigE_LAN',
    'oc-opt-types:PROT_10GE_WAN':   'tapi-dsr:DIGITAL_SIGNAL_TYPE_10_GigE_WAN',
    'oc-opt-types:PROT_40GE':       'tapi-dsr:DIGITAL_SIGNAL_TYPE_40_GigE',
    'oc-opt-types:PROT_100GE':      'tapi-dsr:DIGITAL_SIGNAL_TYPE_100_GigE',
    'oc-opt-types:PROT_STM16':      'tapi-dsr:DIGITAL_SIGNAL_TYPE_STM_16',
    'oc-opt-types:PROT_STM64':      'tapi-dsr:DIGITAL_SIGNAL_TYPE_STM_64',
    'oc-opt-types:PROT_STM256':     'tapi-dsr:DIGITAL_SIGNAL_TYPE_STM_256',
    'oc-opt-types:PROT_OC48':       'tapi-dsr:DIGITAL_SIGNAL_TYPE_OC_48',
    'oc-opt-types:PROT_OC192':      'tapi-dsr:DIGITAL_SIGNAL_TYPE_OC_192',
    'oc-opt-types:PROT_OC768':      'tapi-dsr:DIGITAL_SIGNAL_TYPE_OC_768',
    'oc-opt-types:PROT_OTU1E':      'tapi-dsr:DIGITAL_SIGNAL_TYPE_OTU_1',
    'oc-opt-types:PROT_OTU2':       'tapi-dsr:DIGITAL_SIGNAL_TYPE_OTU_2',
    'oc-opt-types:PROT_OTU2E':      'tapi-dsr:DIGITAL_SIGNAL_TYPE_OTU_2E',
    'oc-opt-types:PROT_OTU3':       'tapi-dsr:DIGITAL_SIGNAL_TYPE_OTU_3',
    'oc-opt-types:PROT_OTU4':       'tapi-dsr:DIGITAL_SIGNAL_TYPE_OTU_4'
}

OPER_STATE_MAP = {
    'oc-platform-types:ACTIVE':     'ENABLED',
    'oc-platform-types:INACTIVE':   'DISABLED',
    'oc-platform-types:DISABLED':   'DISABLED'
}

def find_onep(topology_context, sip_uuid):
    return next(((topology, node, onep)
        for topology in topology_context.topology
        for node in topology.node
        for onep in node.owned_node_edge_point
        for sip in onep.mapped_service_interface_point
        if sip.service_interface_point_uuid == sip_uuid), (None, None, None))

def set_capacity_from_rate_class(total_size, rate_class):
    total_size.value = rate_class.rstrip('G').lstrip('oc-opt-types:TRIB_RATE_')
    total_size.unit = 'GB'

def get_name_value(list_node, value_name):
    if value_name in list_node.name:
        return list_node.name[value_name].value
    return None

class OtTapi(Action):
    def get_uuid(self, cache_name, key):
        cache = self.nodes.get(self.current_device.name)
        if cache_name == 'sips':
            cache = self.sips
        elif cache_name == 'links':
            cache = self.links
        elif cache:
            cache = cache[cache_name]

        cached_uuid = None
        if cache:
            cached_uuid = cache.get(key)
        return cached_uuid if cached_uuid else uuid.uuid4()

    def create_sip(self, is_client_port, transceiver, inventory_id):
        sip_uuid = self.get_uuid('sips', inventory_id)
        self.log.info(f'Creating sip {transceiver.name} [{sip_uuid}]')
        sip = self.tapi_context.service_interface_point.create(sip_uuid)
        sip.name.create('INVENTORY_ID').value = inventory_id
        sip.operational_state = OPER_STATE_MAP.get(transceiver.oper_status)

        interfaces = self.current_device.config.oc_if__interfaces.interface
        if transceiver.name in interfaces:
            sip.administrative_state = (
                'UNLOCKED' if interfaces[transceiver.name].enabled == 'true'
                else 'LOCKED')

        if is_client_port:
            sip.name.create('OT_CLIENT_PORT').value = transceiver.name
            sip.layer_protocol_name = 'DSR'
            if transceiver.logical_channels.channel:
                channel = next(iter(transceiver.logical_channels.channel))
                sip.supported_layer_protocol_qualifier = PROTOCOL_MAP.get(
                    channel.trib_protocol)
                set_capacity_from_rate_class(
                    sip.total_potential_capacity.total_size,
                    channel.rate_class)
                set_capacity_from_rate_class(
                    sip.available_capacity.total_size, channel.rate_class)
        else:
            sip.name.create('OT_LINE_PORT').value = transceiver.name
            sip.layer_protocol_name = 'PHOTONIC_MEDIA'
            sip.supported_layer_protocol_qualifier.create(
                'tapi-photonic-media:PHOTONIC_LAYER_QUALIFIER_OTSi')

        return sip.uuid

    def process_port(self, topology_uuid, node, port):
        is_client_port = False
        transceiver = None

        if port.port_type == 'terminal-client':
            is_client_port = True
            transceiver = port.terminal_client.transceiver
            onep_uuid = self.get_uuid('oneps', f'{port.inventory_id}-DSR')

        elif port.port_type == 'terminal-line':
            transceiver = port.terminal_line.transceiver
            onep_uuid = self.get_uuid(
                'oneps', f'{port.inventory_id}-PHOTONIC_MEDIA-Line')

        if not transceiver or not transceiver.name:
            return

        self.log.info(f'Creating onep {transceiver.name} [{onep_uuid}]')
        onep = node.owned_node_edge_point.create(onep_uuid)
        onep.name.create('INVENTORY_ID').value = port.inventory_id

        onep.mapped_service_interface_point.create(self.create_sip(
            is_client_port, transceiver, port.inventory_id))

        onep_lookup = self.ot_devices[self.current_device.name]['oneps']
        onep_lookup[transceiver.name] = onep_uuid

        if is_client_port:
            onep.layer_protocol_name = 'DSR'
            onep.supported_cep_layer_protocol_qualifier = PROTOCOL_MAP.values()

        else:
            # Line ONEP
            onep.layer_protocol_name = 'PHOTONIC_MEDIA'
            onep.supported_cep_layer_protocol_qualifier = [
                'tapi-photonic-media:PHOTONIC_LAYER_QUALIFIER']

            # OTSi ONEP
            otsi_onep_uuid = self.get_uuid(
                'oneps', f'{port.inventory_id}-PHOTONIC_MEDIA-OTSi')
            self.log.info(f'Creating OTSi onep [{otsi_onep_uuid}]')

            otsi_onep = node.owned_node_edge_point.create(otsi_onep_uuid)
            otsi_onep.name.create('INVENTORY_ID').value = port.inventory_id
            otsi_onep.layer_protocol_name = 'PHOTONIC_MEDIA'
            otsi_onep.supported_cep_layer_protocol_qualifier = [
                'tapi-photonic-media:PHOTONIC_LAYER_QUALIFIER_OTSi',
                'tapi-photonic-media:PHOTONIC_LAYER_QUALIFIER']

            # CEP
            cep_uuid = self.get_uuid('ceps', onep_uuid)
            self.log.info(f'Creating cep [{cep_uuid}]')

            cep = onep.tapi_connectivity__cep_list.connection_end_point.create(
                cep_uuid)
            cep.layer_protocol_qualifier = \
                'tapi-photonic-media:PHOTONIC_LAYER_QUALIFIER'

            cep.client_node_edge_point.create(
                topology_uuid, node.uuid, otsi_onep_uuid)
            cep.parent_node_edge_point.topology_uuid = topology_uuid
            cep.parent_node_edge_point.node_uuid = node.uuid
            cep.parent_node_edge_point.node_edge_point_uuid = onep_uuid

    def create_node(self, topology):
        node_cache = self.nodes.get(self.current_device.name)
        node_uuid = node_cache['uuid'] if node_cache else uuid.uuid4()
        self.log.info(f'Creating node {self.current_device.name} [{node_uuid}]')
        node = topology.node.create(node_uuid)
        node.name.create('NAME').value = self.current_device.name
        node.layer_protocol_name = ['DSR', 'PHOTONIC_MEDIA']
        node.latency_characteristic.create('FIXED_LATENCY')
        node.cost_characteristic.create('HOP_COUNT')

        device_lookup = self.ot_devices[self.current_device.name] = {}
        device_lookup['uuid'] = node_uuid
        device_lookup['oneps'] = {}

        for chassis in self.current_device.openconfig_cache.inventory.chassis:
            for linecard in chassis.linecards.linecard:
                for port in linecard.ports.port:
                    self.process_port(topology.uuid, node, port)

    def create_link(self, sips, ot_topology, inter_domain_link):
        # First add the plug-id to the corresponding SIP
        ot_device_lookup = self.ot_devices[inter_domain_link.ot_device]
        if not inter_domain_link.ot_transceiver in ot_device_lookup['oneps']:
            self.log.info(f'Skipping link {inter_domain_link.plug_id}, '
                          f'unable to find corresponding NEP for OT transceiver '
                          f'{inter_domain_link.ot_transceiver}')
            return

        ot_onep_uuid = ot_device_lookup['oneps'][
            inter_domain_link.ot_transceiver]
        ot_onep = ot_topology.node[
            ot_device_lookup['uuid']].owned_node_edge_point[ot_onep_uuid]
        ot_onep_sip = next(iter(ot_onep.mapped_service_interface_point), None)
        if ot_onep_sip:
            sips[ot_onep_sip.service_interface_point_uuid]\
                .inter_domain_plug_id = inter_domain_link.plug_id

        (ols_topology, ols_node, ols_onep) = find_onep(
            self.root.devices.device[inter_domain_link.ols_controller]
            .live_status.tapi_common__context
            .tapi_topology__topology_context, inter_domain_link.sip_uuid)

        if not ols_onep:
            self.log.info(f'Skipping link {inter_domain_link.plug_id}, '
                          f'unable to find corresponding NEP for SIP '
                          f'{inter_domain_link.sip_uuid}')
            return

        link_uuid = self.get_uuid('links', inter_domain_link.plug_id)
        self.log.info(f'Creating link {inter_domain_link.plug_id} [{link_uuid}]')

        link = ot_topology.link.create(link_uuid)
        link.name.create(
            'INTER_DOMAIN_PLUG_ID').value = inter_domain_link.plug_id
        link.node_edge_point.create(
            ols_topology.uuid, ols_node.uuid, ols_onep.uuid)
        link.node_edge_point.create(
            ot_topology.uuid, ot_device_lookup['uuid'], ot_onep_uuid)

        link.direction = 'BIDIRECTIONAL'
        link.layer_protocol_name = ['PHOTONIC_MEDIA']
        link.transitioned_layer_protocol_name = ['DSR', 'PHOTONIC_MEDIA']
        link.latency_characteristic.create('FIXED_LATENCY')
        link.cost_characteristic.create('HOP_COUNT')
        risk = link.risk_characteristic.create('NONE')
        risk.risk_identifier_list.create('NONE')
        link.validation_mechanism.create('NONE')


    def save_topology_uuids(self, topology):
        # Save all existing UUIDs, then delete and recreate everything
        for node in topology.node:
            node_name = get_name_value(node, 'NAME')
            if node_name:
                node_cache = self.nodes[node_name] = {}
                node_cache['uuid'] = node.uuid
                node_cache['oneps'] = {}
                node_cache['ceps'] = {}

                for onep in node.owned_node_edge_point:
                    onep_inventory_id = get_name_value(onep, 'INVENTORY_ID')
                    onep_layer = onep.layer_protocol_name
                    if onep_layer == 'PHOTONIC_MEDIA':
                        if ('tapi-photonic-media:PHOTONIC_LAYER_QUALIFIER_OTSi'
                                in onep.supported_cep_layer_protocol_qualifier):
                            onep_layer = f'{onep_layer}-OTSi'
                        else:
                            onep_layer = f'{onep_layer}-Line'
                    if onep_inventory_id:
                        node_cache['oneps'][
                            f'{onep_inventory_id}-{onep_layer}'] = onep.uuid

                    for cep in (onep.tapi_connectivity__cep_list
                            .connection_end_point):
                        node_cache['ceps'][onep.uuid] = cep.uuid

        for link in topology.link:
            inter_domain_plug_id = get_name_value(link, 'INTER_DOMAIN_PLUG_ID')
            if inter_domain_plug_id:
                self.links[inter_domain_plug_id] = link.uuid

    def save_sip_uuids(self):
        for sip in self.tapi_context.service_interface_point:
            sip_inventory_id = get_name_value(sip, 'INVENTORY_ID')
            if sip_inventory_id:
                self.sips[sip_inventory_id] = sip.uuid

    #pylint: disable=attribute-defined-outside-init
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)

        # UUID cache
        self.nodes = {}
        self.sips = {}
        self.links = {}

        # OT device lookups for topology links
        self.ot_devices = {}

        with ncs.maapi.single_write_trans(uinfo.username, 'python') as th:
            self.root = ncs.maagic.get_root(th)
            self.tapi_context = self.root.tapi_common__context
            topology_context = self.tapi_context.tapi_topology__topology_context

            topology_uuid = None
            for topology in topology_context.topology:
                topology_name = get_name_value(topology, 'TOPOLOGY_NAME')
                if topology_name == 'OpenConfig Topology':
                    topology_uuid = topology.uuid
                    self.save_topology_uuids(topology)
                    self.save_sip_uuids()

            topology_context.topology.delete()
            self.tapi_context.service_interface_point.delete()

            if not topology_uuid:
                topology_uuid = uuid.uuid4()

            topology = topology_context.topology.create(topology_uuid)
            topology.name.create('TOPOLOGY_NAME').value = 'OpenConfig Topology'
            topology.layer_protocol_name = ['DSR', 'PHOTONIC_MEDIA']

            for device in self.root.devices.device:
                if device.device_type.netconf.ned_id == \
                        'openconfig-ot-cisco-nc-1.0:openconfig-ot-cisco-nc-1.0':
                    self.current_device = device
                    self.create_node(topology)

            for link in topology_context.inter_domain_links.link:
                self.create_link(
                    self.tapi_context.service_interface_point, topology, link)

            th.apply()


class OtTapiDelete(Action):
    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)

        with ncs.maapi.single_write_trans(uinfo.username, 'python') as th:
            tapi_context = ncs.maagic.get_root(th).tapi_common__context

            tapi_context.tapi_topology__topology_context.topology.delete()
            tapi_context.service_interface_point.delete()

            th.apply()
