# -*- mode: python; python-indent: 4 -*-
import json
import socket
import lxml.etree as ET
import ncs
import _ncs
from ncs.dp import Action
_ncs = __import__('_ncs') # pylint: disable=invalid-name

def sort_key_nodes_first(tags):
    # FIXME: Read actual key names and order from CDB schema
    key_order = {
        'uuid': 1,
        'topology-uuid': 1,
        'node-uuid': 2,
        'node-edge-point-uuid': 3,
        'service-interface-point-uuid': 1,
        'risk-characteristic-name': 1,
        'cost-name': 1,
        'traffic-property-name': 1,
        'validation-mechanism': 1,
        'local-id': 1,
        'node-rule-group-uuid': 1,
        'value-name': 1,
        'unit': 1,
        'upper-frequency': 1,
        'lower-frequency': 2,
        'lower-central-frequency': 1,
        'upper-central-frequency': 2,
        'application-node': 1
    }
    return sorted(tags, key=lambda tag:
                  key_order[tag] if tag in key_order else 10)

def get_topology_context_data(device):
    get_any_action = device.live_status.onf_tapi_rc_stats__exec.get_any
    get_any_input = get_any_action.get_input()
    get_any_input.url = '/data/tapi-common:context/tapi-topology:topology-context'
    get_any_output = get_any_action(get_any_input)
    return json.loads(get_any_output.result)

# ---------------
# ACTIONS EXAMPLE
# ---------------
class TopologyContext(Action):
    def get_default_ns_map(self, module):
        ns_map = {
            'tapi-common':          'urn:onf:otcc:yang:tapi-common',
            'tapi-connectivity':    'http://example.com/oif-tapi',
            'tapi-photonic-media':  'http://example.com/oif-tapi',
            'tapi-odu':             'http://example.com/oif-tapi',
            'tapi-topology':        'http://example.com/oif-tapi',
            'oif-tapi':             'http://example.com/oif-tapi',
        }

        if module in ns_map:
            return {None : ns_map[module]}

        if self.strict:
            raise Exception('Unknown module {}'.format(module))

        return None

    def add_element_with_default_ns(self, parent, tag):
        default_ns_map = None

        if ':' in tag:
            [module, tag] = tag.split(':')
            default_ns_map = self. get_default_ns_map(module)

            if default_ns_map is None:
                return None

        return ET.SubElement(parent, tag, nsmap=default_ns_map)

    def add_xml_nodes(self, parent, json_node):
        def add_xml_element(key, contents):
            xml_element = self.add_element_with_default_ns(parent, key)
            if xml_element is not None:
                if isinstance(contents, dict):
                    self.add_xml_nodes(xml_element, contents)
                else:
                    if isinstance(contents, bool):
                        xml_element.text = 'true' if contents else 'false'
                    else:
                        xml_element.text = str(contents)

        for key in sort_key_nodes_first(json_node.keys()):
            if isinstance(json_node[key], list):
                for list_item in json_node[key]:
                    add_xml_element(key, list_item)
            else:
                add_xml_element(key, json_node[key])

    def __init__(self, daemon, actionpoint, log=None, init_args=None):
        self.strict = False
        super(TopologyContext, self).__init__(
            daemon, actionpoint, log, init_args)

    @Action.action
    def cb_action(self, uinfo, name, kp, input, output, trans):
        self.log.info('action name: ', name)
        self.strict = input.strict_yang_check

        device_name = str(kp[1][0])

        root = ET.Element('oif-tapi', nsmap=self.get_default_ns_map('oif-tapi'))
        device_element = ET.SubElement(root, 'device')
        device_name_element = ET.SubElement(device_element, 'name')
        device_name_element.text = device_name

        with ncs.maapi.single_read_trans(uinfo.username, 'python') as th:
            json_data = get_topology_context_data(
                ncs.maagic.get_root(th).devices.device[device_name])

        self.add_xml_nodes(device_element, json_data)

        with ncs.maapi.single_write_trans(uinfo.username, 'python',
                                          db=_ncs.OPERATIONAL) as th:
            load_flags = (_ncs.maapi.CONFIG_XML |
                          _ncs.maapi.CONFIG_MERGE |
                          _ncs.maapi.CONFIG_OPER_ONLY)
            if not self.strict:
                load_flags |= _ncs.maapi.CONFIG_XML_LOAD_LAX

            config_id = th.load_config_stream(load_flags)
            sock = socket.socket()
            _ncs.stream_connect(sock, config_id, 0,
                                '127.0.0.1', _ncs.NCS_PORT)

            sock.send(bytes(ET.tostring(root, encoding='UTF-8')))
            sock.close()
            self.log.info(th.maapi.load_config_stream_result(config_id))
            th.apply()


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):
    def setup(self):
        # The application class sets up logging for us. It is accessible
        # through 'self.log' and is a ncs.log.Log instance.
        self.log.info('Main RUNNING')

        # When using actions, this is how we register them:
        #
        self.register_action('get-topology-context', TopologyContext)

        # If we registered any callback(s) above, the Application class
        # took care of creating a daemon (related to the service/action point).

        # When this setup method is finished, all registrations are
        # considered done and the application is 'started'.

    def teardown(self):
        # When the application is finished (which would happen if NCS went
        # down, packages were reloaded or some error occurred) this teardown
        # method will be called.

        self.log.info('Main FINISHED')
