"""Transform library + registry.

Ordered by preference; the proposer offers the first whose pattern matches.
"""
from .map_to_unordered_map import MapToUnorderedMap
from .pass_by_const_ref import PassByConstRef
from .reserve import ReserveBeforePushback, ReserveString, ReserveUnorderedMap

ALL = [ReserveBeforePushback(), ReserveString(), ReserveUnorderedMap(),
       MapToUnorderedMap(), PassByConstRef()]
