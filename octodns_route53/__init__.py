#
#
#

from .provider import Route53Provider, Route53ProviderException
from .record import Route53AliasRecord
from .source import Ec2Source, ElbSource

# TODO: remove __VERSION__ with the next major version release
__version__ = __VERSION__ = '1.0.0'

# quell warnings
Ec2Source
ElbSource
Route53AliasRecord
Route53Provider
Route53ProviderException
