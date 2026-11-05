"""Part SDK: what every component on the bench provides.

A part declares its pins, catalogue metadata, ratings and a behavior model:
  elements()   electrical stamps for the solver (pins written '@PIN')
  sense()      react to solved input voltages (edges, triggers, clocks)
  dynamic()    hashable output state, so changes trigger a re-solve
  state()      what the 3D bench and inspector display
Protocol parts additionally implement i2c_*, spi_transfer or uart_rx.
"""
from __future__ import annotations


class Part:
    kind = ''
    prefix = 'u'
    pins: tuple = ()
    hidden: tuple = ()        # internal nodes (not connectable), e.g. behind a base resistor
    internal: tuple = ()
    inputs: tuple = ()
    defaults: dict = {}
    choices: dict = {}
    stimuli_spec: dict = {}   # name -> (min, max, default, unit, label)
    supply = None             # (vcc pin, gnd pin, v_min, v_max, v_abs)
    pin_limits: dict = {}     # pin -> absolute maximum volts relative to part ground
    source_pins: tuple = ()
    damaged_behavior = 'It no longer works.'
    meta: dict = {}

    def __init__(self, circuit, pid, props):
        self.circuit = circuit
        self.id = pid
        self.props = dict(self.defaults)
        self.configure(props)
        self.stimuli = {name: spec[2] for name, spec in self.stimuli_spec.items()}
        self.damaged = None
        self.setup()

    def setup(self):
        pass

    @property
    def machine(self):
        return self.circuit.machine

    @property
    def label(self):
        return f'{self.meta.get("name", self.kind)} ({self.id})'

    def node(self, pin):
        return f'{self.id}.{pin}'

    # -- configuration ---------------------------------------------------------------
    def configure(self, props):
        if not isinstance(props, dict):
            raise ValueError('Part properties must be an object.')
        for key, value in props.items():
            if key not in self.defaults:
                raise ValueError(f'{self.meta.get("name", self.kind)} has no property {key!r:.30}.')
            default = self.defaults[key]
            if key in self.choices:
                if value not in self.choices[key]:
                    raise ValueError(f'{key} must be one of {", ".join(map(str, self.choices[key]))}.')
            elif isinstance(default, bool):
                if type(value) is not bool:
                    raise ValueError(f'{key} must be true or false.')
            elif isinstance(default, (int, float)):
                if type(value) not in (int, float) or value != value or not 0 <= value <= 1e9:
                    raise ValueError(f'{key} must be a non-negative number.')
            elif isinstance(default, str) and (not isinstance(value, str) or len(value) > 200):
                raise ValueError(f'{key} must be text.')
            self.props[key] = value
        self.configured()

    def configured(self):
        pass

    def set_stimulus(self, name, value):
        if name not in self.stimuli_spec:
            raise ValueError(f'{self.meta.get("name", self.kind)} has no input {name!r:.30}.')
        low, high = self.stimuli_spec[name][:2]
        if type(value) not in (int, float) or value != value or not low <= value <= high:
            raise ValueError(f'{name} must be between {low} and {high}.')
        self.stimuli[name] = value
        self.stimulated(name)

    def stimulated(self, name):
        pass

    # -- electrical ------------------------------------------------------------------
    def signature(self):
        # Powered state is part of the signature: a part whose supply comes up
        # during a solve gets its outputs stamped in the following iteration.
        return (self.damaged is not None, tuple(self.stimuli.values()), self.powered(), self.dynamic())

    def dynamic(self):
        return ()

    def elements(self):
        return []

    def sense(self, volts, now):
        pass

    def check(self, volts):
        return []

    def v(self, pin):
        return self.circuit.net_voltage.get(self.node(pin), 0.0)

    def supply_voltage(self):
        if not self.supply:
            return 0.0
        return self.v(self.supply[0]) - self.v(self.supply[1])

    def powered(self):
        if not self.supply:
            return True
        return self.supply_voltage() >= self.supply[2] - 0.05

    def operational(self):
        return self.damaged is None and self.powered()

    def logic(self, pin, threshold=None):
        """Digital reading of an input relative to this part's ground and supply."""
        ground = self.v(self.supply[1]) if self.supply else 0.0
        level = self.v(pin) - ground
        if threshold is None:
            threshold = (self.supply_voltage() if self.supply else 3.3) * 0.5
        return int(level >= threshold)

    def output(self, pin, level, ohms=50.0, tag=None, high=None):
        """Push-pull output stamp: switches the pin to the part's VCC or GND pin.

        `high` gives a regulated logic level (e.g. a 3.3 V output on a 5 V module)."""
        if self.supply:
            vcc, gnd = self.supply[0], self.supply[1]
            if not level:
                return ('R', f'@{pin}', f'@{gnd}', ohms, tag or pin)
            if high is None:
                return ('R', f'@{pin}', f'@{vcc}', ohms, tag or pin)
            return ('V', f'@{pin}', f'@{gnd}', high if self.powered() else 0.0, ohms, tag or pin)
        return ('V', f'@{pin}', -1, (3.3 if high is None else high) if level else 0.0, ohms, tag or pin)

    def changed(self):
        """Outputs changed outside a solve (scheduled event): re-resolve the board."""
        self.circuit._cache.clear()
        self.machine.observe()

    def schedule_in(self, ns, callback):
        self.machine.schedule_in(ns, callback)

    def now(self):
        return self.machine.time_ns()

    # -- damage ------------------------------------------------------------------------
    def damage(self, reason):
        self.damaged = reason

    def repair(self):
        self.damaged = None
        self.setup()

    # Attributes holding in-flight protocol state; scheduled events die with the
    # old machine at an MCU reset, so these return to their idle values.
    transient = {}

    def reset_transient(self):
        for name, value in self.transient.items():
            setattr(self, name, list(value) if isinstance(value, list) else value)

    def state(self):
        return {}
