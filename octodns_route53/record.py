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
            if 'amazonaws.com.' in (value.get('name') or ''):
                if not value.get('hosted-zone-id'):
                    reasons.append('service alias without hosted-zone-id')
            else:
                if value.get('hosted-zone-id'):
                    reasons.append('hosted-zone-id on a non-service value')

        return reasons

    @classmethod
    def process(cls, values):
        return [_Route53AliasValue(v) for v in values]

    def __init__(self, value):
        self.name = value.get('name') or ''
        self._type = value['type']
        self.evaluate_target_health = value.get('evaluate-target-health',
                                                False)
        self.hosted_zone_id = value.get('hosted-zone-id')

    @property
    def data(self):
        return {
            'hosted-zone-id': self.hosted_zone_id,
            'evaluate-target-health': self.evaluate_target_health,
            'name': self.name,
            'type': self._type,
        }

    def __hash__(self):
        return hash((self._type, self.name, self.hosted_zone_id))

    def _equality_tuple(self):
        return (self._type, self.name, self.hosted_zone_id)

    def __repr__(self):
        return f'"{self.name}" {self._type} {self.hosted_zone_id or ""}'


class Route53AliasRecord(ValuesMixin, Record):
    _type = 'Route53Provider/ALIAS'
    _value_type = _Route53AliasValue


Record.register_type(Route53AliasRecord)
