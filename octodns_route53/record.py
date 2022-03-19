from octodns.record import Record, ValuesMixin
from octodns.equality import EqualityTupleMixin


class _Route53AliasValue(EqualityTupleMixin):

    @classmethod
    def validate(cls, data, _type):
        if not isinstance(data, (list, tuple)):
            data = (data,)
        reasons = []
        for value in data:
            if 'type' not in value:
                reasons.append('missing type')

        return reasons

    @classmethod
    def process(cls, values):
        return [_Route53AliasValue(v) for v in values]

    def __init__(self, value):
        self.name = value.get('name', '')
        self._type = value['type']
        self.evaluate_target_health = value.get('evaluate-target-health',
                                                False)

    @property
    def data(self):
        return {
            'name': self.name,
            'type': self._type,
        }

    def __hash__(self):
        return hash((self._type, self.name))

    def _equality_tuple(self):
        return (self._type, self.name)

    def __repr__(self):
        return f'{self.name} {self._type}'


class Route53AliasRecord(ValuesMixin, Record):
    _type = 'Route53Provider/ALIAS'
    _value_type = _Route53AliasValue


Record.register_type(Route53AliasRecord)
