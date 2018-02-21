import ncs.template
from ncs.application import PlanComponent
from ncs.maapi import Maapi
from ncs.dp import Daemon, take_worker_socket, return_worker_socket
from _ncs.dp import register_valpoint_cb, register_trans_validate_cb, trans_set_fd
import functools
import re
import os
_tm = __import__(ncs.tm.TM)


# ---------------------------------------------
# UTILITY FUNCTIONS
# ---------------------------------------------
def plan_data_service(*custom_states):
    """
    Decorator for cb_create callback. Initialize a self plan component.
    :param custom_states: additional states for the plan component
    :return: cb_create wrapper
    """
    def decorator(cb_create_method):
        @functools.wraps(cb_create_method)
        def wrapper(self, tctx, root, service, proplist):
            self.log.info('Service create ({})'.format(service._path))
            self_plan = init_plan(PlanComponent(service, 'self', 'ncs:self'), *custom_states)

            try:
                proplist = cb_create_method(self, tctx, root, service, proplist, self_plan)
                if proplist is None:
                    return
            except NcsServiceError as e:
                self.log.error(e)
                self_plan.set_failed('ncs:ready')
                raise
            else:
                self_plan.set_reached('ncs:ready')

            return proplist

        return wrapper

    return decorator


def init_plan(plan_component, *custom_states):
    """
    Initialize the states of an NCS PlanComponent object
    :param plan_component: An NCS PlanComponent object
    :param custom_states: One or more strings representing additional states supported by the plan component
    :return: The PlanComponent object
    """
    for plan_state in ['ncs:init'] + list(custom_states) + ['ncs:ready']:
        plan_component.append_state(plan_state)

    plan_component.set_reached('ncs:init')

    return plan_component


def apply_template(template_name, context, var_dict=None):
    """
    Facilitate applying templates by setting template variables via an optional dictionary

    :param template_name: Name of the template file
    :param context: Context in which the template is rendered
    :param var_dict: Optional dictionary containing additional variables to be passed to the template
    """
    template = ncs.template.Template(context)
    t_vars = ncs.template.Variables()

    if var_dict is not None:
        for name, value in var_dict.items():
            t_vars.add(name, value)

    template.apply(template_name, t_vars)


def split_intf_name(intf_name):
    """
    Split a full interface name (e.g. GigabitEthernet0/1/2/3) into interface type (e.g. GigabitEthernet)
    and id (e.g. 0/1/2/3)
    :param intf_name: string containing the full interface name
    :return: 2-tuple (<interface type>, <interface id>) or None if the name couldn't be parsed
    """
    m = re.match(r'(?P<type>[a-zA-Z-]+)(?P<id>[0-9]+[^\s]*)', intf_name)
    if m is not None:
        return m.group('type'), m.group('id')

    return None


def is_intf_sub(intf_name):
    """
    Return True if the provided interface name refers to a subinterface
    :param intf_name: interface name
    :return: True or False
    """
    return '.' in intf_name


def get_key_yang(node):
    """
    Return the yang names corresponding to the node's key(s)

    :param node: a Maagic List
    :return: list of key yang names or None if node doesn't have any key element
    """

    # keys() returns None if node doesn't have any key (e.g. not a List)
    key_hashes = node._cs_node.info().keys()

    return key_hashes and [_tm.hash2str(key_hash) for key_hash in key_hashes]


def get_xpath(service_node):
    """
    Get an xpath that resolves to the provided service node element

    Example:
        service_node: /ncs:services/ciscoas:l3-default{CUSTOMER1-L3-DEFAULT-1 Vancouver}
        return: /ncs:services/ciscoas:l3-default[service-id='CUSTOMER1-L3-DEFAULT-1'][dc-name='Vancouver']

    Please note that this function only supports service_node with a single list in its keypath. Keypaths with
    concatenated lists are not supported and will produce unexpected results.

    :param service_node: a service node object
    :return: xpath string
    """

    def replace_match(match):
        key_values = match.group(1).split()
        return ''.join(map(lambda name_value: "[{}='{}']".format(name_value[0], name_value[1]),
                           zip(service_key_names, key_values)))

    service_key_names = get_key_yang(service_node)

    return re.sub(r'{([^}]+)}', replace_match, service_node._path)


class DiffOps(object):
    """
    Convenience class for converting NSO diff-iterate operations to string
    """
    op_dict = {
        ncs.MOP_ATTR_SET: 'MOP_ATTR_SET',
        ncs.MOP_CREATED: 'MOP_CREATED',
        ncs.MOP_DELETED: 'MOP_DELETED',
        ncs.MOP_MODIFIED: 'MOP_MODIFIED',
        ncs.MOP_MOVED_AFTER: 'MOP_MOVED_AFTER',
        ncs.MOP_VALUE_SET: 'MOP_VALUE_SET',
    }

    @staticmethod
    def get_op_str(int_op):
        """
        Return the correspondign string value of a diff-iterate operation

        :param int_op: integer representing an ncs diff-iterate operation
        :return: string value of the operation
        """
        return DiffOps.op_dict.get(int_op, 'unknown')

    def __init__(self, op):
        self.op = op

    def __str__(self):
        return '{}({})'.format(DiffOps.get_op_str(self.op), self.op)


class Validation(object):
    """
    Convenience class for custom validation callbacks

    1) Create a custom validation class extending Validation
    Your custom validation class needs to implement the validate method. Optionally it can have init and stop
    methods, which get called at the beginning and end of the transaction validation phase.

    class CustomValidation(Validation):
        def validate(self, tctx, kp, newval, root):
            self.log.info('validate a called')
            return ncs.CONFD_OK

        def init(self, tctx):
            self.log.info('custom init a called')

        def stop(self, tctx):
            self.log.info('custom stop a called')

    2) Decorate your application class with custom_validators and register your custom validation class:
    The decorator allows calling self.register_validation within the setup method in a similar way as the builtin
    register_service and register_action methods.

    @Validation.custom_validators
    class Main(ncs.application.Application):
        def setup(self):
            ...
            self.register_validation('custom-validate-a', CustomValidation)
            ...
    """

    @staticmethod
    def custom_validators(cls):

        if not issubclass(cls, ncs.application.Application):
            raise TypeError('custom_validators can only decorate ncs.application.Application subclasses')

        original_init = cls.__init__
        original_setup = cls.setup
        original_teardown = cls.teardown

        def __init__(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            self._daemons = []

        def setup(self):
            r = original_setup(self)

            for daemon in self._daemons:
                daemon.start()

            return r

        def teardown(self):
            r = original_teardown(self)

            for daemon in self._daemons:
                daemon.finish()

            return r

        def register_validation(self, validation_point, validation_cls):
            daemon = Daemon('ncs-dp-{0}-{1}:{2}'.format(os.getpid(), self._ncs_pname, validation_point), log=self.log)
            v = validation_cls(daemon, validation_point)
            register_trans_validate_cb(daemon.ctx(), v)
            register_valpoint_cb(daemon.ctx(), validation_point, v)
            self._daemons.append(daemon)

        cls.__init__ = __init__
        cls.setup = setup
        cls.teardown = teardown
        cls.register_validation = register_validation

        return cls

    def __init__(self, daemon, validation_point):
        self.validation_point = validation_point
        self.log = daemon.log
        self.maapi = None
        self.trans = None
        self.daemon = daemon

    def cb_init(self, tctx):
        if self.maapi is None:
            self.maapi = Maapi()
        self.trans = self.maapi.attach(tctx)

        name = 'th-{0}'.format(tctx.th)
        wsock = take_worker_socket(self.daemon, name, self._make_key(tctx))
        try:
            init_cb = getattr(self, 'init', None)
            if callable(init_cb):
                init_cb(tctx)

            # Associate worker socket with the transaction
            trans_set_fd(tctx, wsock)

        except Exception as e:
            return_worker_socket(self.daemon, self._make_key(tctx))
            raise

    def cb_stop(self, tctx):
        try:
            stop_cb = getattr(self, 'stop', None)
            if callable(stop_cb):
                stop_cb(tctx)

        finally:
            try:
                self.maapi.detach(tctx)
            except Exception as e:
                pass

            self.trans = None
            return_worker_socket(self.daemon, self._make_key(tctx))

    def cb_validate(self, tctx, kp, newval):
        validate_cb = getattr(self, 'validate', None)
        if callable(validate_cb):
            root = ncs.maagic.get_root(self.trans, shared=False)
            return validate_cb(tctx, kp, newval, root)

        raise NotImplementedError()

    def _make_key(self, tctx):
        return '{0}-{1}'.format(id(self), tctx.th)


# ---------------------------------------------
# Exceptions
# ---------------------------------------------
class NcsServiceError(Exception):
    """ Exception indicating error during service create """
    pass


class ValidationError(Exception):
    """ Exception indicating error on custom validation """
    pass
