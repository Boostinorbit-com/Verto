"""Transform library + registry.

Ordered by preference; the proposer offers the first whose pattern matches.
"""
from .map_to_unordered_map import MapToUnorderedMap
from .reserve_before_pushback import ReserveBeforePushback

ALL = [ReserveBeforePushback(), MapToUnorderedMap()]
